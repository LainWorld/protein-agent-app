"""Run one normal chat on loopback, or inspect the resulting job without resubmitting it."""

import asyncio
from contextlib import asynccontextmanager, closing, contextmanager
import fcntl
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import sys
from uuid import UUID, uuid4

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from round6_evidence import (FLASH, MESSAGE, TIMEOUT, backend_pins, check_browser, check_chat, check_env,
                             check_gpu, check_http, digest, load, pack, read_json, require, uid, verify, write_json)
from ubiquitin import SEED, cif_path, now
from app.config import Settings
from app.main import create_app
from app.schemas import ChatRequest
from app.sequences import InputIssue, normalize

PROJECT = Path(__file__).resolve().parents[1]
DEEPSEEK = 'https://api.deepseek.com'


def safe_tag(value):
    return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_./:-]{1,256}', value) else None


def record_completions(proof):
    """Observe the production HTTP client's responses. Never serialize headers, prompts or free text."""
    async def record(response):
        if str(response.request.url) != DEEPSEEK + '/chat/completions':
            return
        request = json.loads(response.request.content)
        sent = []
        for msg in request['messages']:
            if msg['role'] == 'tool':
                out = json.loads(msg['content'])
                sent.append(dict(call_id=safe_tag(msg['tool_call_id']), job_id=safe_tag(out.get('id')), code=safe_tag(out.get('code'))))
        rec = dict(utc=now(), url=str(response.request.url), http_status=response.status_code,
                   requested_model=safe_tag(request['model']), sent_results=sent, calls=[],
                   user_message_matches=any(m['role']=='user' and m['content']==MESSAGE for m in request['messages']))
        if response.status_code == 200:
            await response.aread()
            try:
                body = response.json()
                choice = body['choices'][0]
                rec.update(completion_id=safe_tag(body.get('id')), response_model=safe_tag(body.get('model')),
                           finish_reason=safe_tag(choice.get('finish_reason')))
                for item in choice['message'].get('tool_calls') or []:
                    fn = item['function']
                    call = dict(id=safe_tag(item['id']), name=safe_tag(fn['name']))
                    rec['calls'].append(call)
                    if fn['name'] == 'predict_structure':
                        try:
                            args = json.loads(fn['arguments'])
                            call['model'] = safe_tag(args.get('model'))
                            call['sequence_sha256'] = digest(normalize(args.get('sequence','')).encode())
                        except (ValueError, AttributeError, TypeError):
                            call['unrecognized_arguments'] = True
            except (KeyError, IndexError, TypeError, ValueError, AttributeError, InputIssue):
                rec['unrecognized_response'] = True
        with (proof/'provider.jsonl').open('a', encoding='utf-8') as f:
            print(json.dumps(rec), file=f)
    return record


@contextmanager
def exclusive(work):
    work.mkdir(parents=True, exist_ok=True)
    with (work/'.round6.lock').open('a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('本会话已有验收进程，请等当前单元结束') from None
        yield


@asynccontextmanager
async def loopback(app):
    app.mount('/', StaticFiles(directory=PROJECT/'frontend/dist', html=True))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        host, port = listener.getsockname()
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='warning'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(15):
                while not server.started:
                    if serving.done():
                        await serving
                        raise ValueError('后端启动失败')
                    await asyncio.sleep(.05)
            yield f'http://{host}:{port}'
        finally:
            server.should_exit = True
            await serving


def note(proof, stage, reason):
    write_json(proof/'issue.json', dict(utc=now(), stage=stage, reason=reason))
    print('PARTIAL ·', stage, reason, flush=True)


async def read_structure(client, proof, job):
    path = f"/api/jobs/{job['id']}/structure?conversation_id={job['conversation_id']}"
    facts = {}
    for disposition in ('inline','attachment'):
        url = path + ('&download=true' if disposition == 'attachment' else '')
        response = await client.get(url)
        facts[disposition] = dict(path=url, status=response.status_code, disposition=response.headers.get('content-disposition'),
                                  sha256=digest(response.content))
        check_http(facts, job)
        write_json(proof/'structure-http.json', facts)


async def capture(app, client, work, *, allow_submit=True):
    proof = work/'proof'
    req = ChatRequest.model_validate(read_json(proof/'request.json'))
    require(req.message == MESSAGE and req.request_id and req.conversation_id is None, '第六轮请求与项目泛素不符')
    store = app.state.store
    previous = store.replay(req.request_id, req)
    if previous is None:
        require(allow_submit, '只读复核找不到已提交的聊天')
        require(not any((proof/n).exists() for n in ('job.json','reply.json','turn.json')),
                '已保存过提交结果，但任务库缺失。请使用已下载的 ZIP')
        with closing(store.connect()) as db:
            require(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0] == 0 and
                    not any(app.state.jobs.root.iterdir()), '已有聊天或任务目录，请恢复原请求')
        health = (await client.get('/api/health')).json()
        require(health['llm_configured'] and health['prediction_modes']['protenix'] == 'real'
                and health['prediction_configured']['protenix'], '聊天或 Protenix Real 未就绪')
        # Only a new explicit attempt with no committed turn may issue this single POST.
        (proof/'provider.jsonl').unlink(missing_ok=True)
        app.state.agent.llm.http.event_hooks['response'].append(record_completions(proof))
        print('POST /api/chat · request', req.request_id, flush=True)
        res = await client.post('/api/chat', json=req.model_dump(mode='json', exclude_none=True))
        if res.status_code != 200:
            reason = safe_tag(res.json().get('error',{}).get('code')) or 'chat_http_error'
            note(proof, 'chat', f'HTTP {res.status_code} · {reason}')
            return
        reply = res.json()
    else:
        reply = previous.model_dump(mode='json')
        print('读取已提交的聊天', req.request_id, flush=True)
    write_json(proof/'reply.json', reply)
    cid = uid(reply['conversation_id'])
    history = await client.get('/api/conversations/'+cid)
    history.raise_for_status()
    write_json(proof/'conversation.json', history.json())
    with closing(store.connect()) as db:
        turn = db.execute('SELECT tools_json,utc FROM turns WHERE request_id=? AND conversation_id=?',
                          (str(req.request_id), cid)).fetchone()
    write_json(proof/'turn.json', dict(request_id=str(req.request_id), conversation_id=cid,
                                       utc=turn['utc'], tools=json.loads(turn['tools_json'])))
    if reply['outcome'] != 'job_submitted' or len(reply['job_ids']) != 1:
        note(proof, 'chat', '提交结果 '+str(safe_tag(reply['outcome'])))
        return
    jid = uid(reply['job_ids'][0])
    print('CONVERSATION', cid, 'JOB', jid, flush=True)
    path = f'/api/jobs/{jid}?conversation_id={cid}'
    last = None
    async with asyncio.timeout(TIMEOUT + 45):
        while True:
            response = await client.get(path)
            response.raise_for_status()
            job = response.json()
            require(job['id'] == jid and job['conversation_id'] == cid, '轮询任务不匹配')
            if job['status'] != last:
                write_json(proof/'job.json', job)
                print('JOB', jid, job['status'], flush=True)
                last = job['status']
            if last in ('succeeded','failed'):
                break
            await asyncio.sleep(2)
    directory = store.path.parent/'jobs'/jid
    for name in ('input.json', 'protenix-input.json', 'events.jsonl', 'cli-events.jsonl'):
        if (directory/name).is_file():
            shutil.copyfile(directory/name, proof/name)
    if last == 'failed':
        note(proof, 'job', job['error'])
        return
    shutil.copyfile(cif_path(directory, SEED), proof/'prediction.cif')
    shutil.copyfile(directory/'structure.pdb', proof/'structure.pdb')
    path = pack(work)  # A browser or HTTP failure must not discard a completed GPU prediction.
    data = load(path)
    check_chat(data)
    atoms = check_gpu(data, job)
    print('CHAT + GPU OK ·', jid, '· 76 aa ·', atoms, 'atoms ·', job['sha256'], flush=True)
    await read_structure(client, proof, job)
    print('STRUCTURE HTTP OK · inline + attachment', flush=True)
    return job


async def browser(base, proof, job, *, location, env, node=None):
    launcher = ([str(node), str(PROJECT/'frontend/tests/browser-check.mjs')] if node is not None else
                ['bash', str(PROJECT/'scripts/check-browser.sh')])
    args = ['--round6', job['conversation_id'], base.rsplit(':',1)[1], str(proof), job['id'], job['sha256'], location]
    proc = await asyncio.create_subprocess_exec(*launcher, *args, env=env)
    try:
        async with asyncio.timeout(180):
            code = await proc.wait()
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    require(code == 0, '浏览器检查未完成，可单独重跑查看或在 Mac 复核')


def snapshot_env(work, env_root):
    proof = work/'proof'
    for name, src in (('hardware.json',env_root/'hardware.json'), ('versions.json',env_root/'versions.json'),
                      ('resources.json',env_root/'cache/resources.json')):
        if not (proof/name).exists():
            shutil.copyfile(src, proof/name)
    check_env(*(read_json(proof/(n+'.json')) for n in ('versions','hardware','resources')))
    pins = backend_pins()
    versions = {name:metadata.version(name) for name in pins}
    require(versions == pins, '后端依赖与锁文件不符')
    if not (proof/'backend-versions.json').exists():
        write_json(proof/'backend-versions.json', dict(python=sys.version.split()[0], packages=versions))


def prepare_request(work):
    path = work/'proof/request.json'
    if path.exists():
        return
    db = work/'data/app.sqlite3'
    previous = []
    if db.exists():
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as conn:
            previous = conn.execute('SELECT request_id,user_text FROM turns LIMIT 2').fetchall()
    if previous:
        require(len(previous) == 1 and previous[0][1] == MESSAGE, '数据库不属于本次单任务验收')
    write_json(path, dict(message=MESSAGE, request_id=uid(previous[0][0]) if previous else str(uuid4())))


async def check_live_view(base, work, job, *, location, env, node=None):
    proof = work/'proof'
    await browser(base, proof, job, location=location, env=env, node=node)
    receipt = check_browser(load(pack(work)), job, location)
    require(receipt.get('refresh') and receipt.get('download_sha256') == job['sha256'], '浏览器证据不完整')
    print('MOLSTAR + DOWNLOAD OK', job['id'], flush=True)


async def colab(stage, work, env_root):
    with exclusive(work):
        proof = work/'proof'
        proof.mkdir(exist_ok=True)
        prepare_request(work)
        if stage == 'run':
            snapshot_env(work, env_root)
            # Pipe from Colab Secrets. Neither argv nor the predictor/browser environment contains the secret.
            key = sys.stdin.readline().strip()
        else:
            require((proof/'request.json').is_file() and (work/'data/app.sqlite3').is_file(), '请先完成聊天单元')
            key = ''
        config = Settings('deepseek', DEEPSEEK, FLASH, key, work/'data/app.sqlite3', esmfold2_mode='real',
                          protenix_mode='real', protenix_executable=str(env_root/'venv/bin/protenix'),
                          protenix_root=env_root/'cache', job_timeout=TIMEOUT)
        app = create_app(config)
        try:
            async with loopback(app) as base, httpx.AsyncClient(base_url=base, trust_env=False, timeout=75) as client:
                job = await capture(app, client, work, allow_submit=stage=='run')
                if job is None:
                    raise SystemExit(2)
                if (work/'browser-ready.json').exists():
                    browser_env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(work/'browser-cache'))
                    await check_live_view(base, work, job, location='colab_backend', env=browser_env, node=work/'browser-tools/node')
                    (proof/'issue.json').unlink(missing_ok=True)
                else:
                    note(proof, 'browser', '浏览器环境尚未就绪，已保留原任务')
        except (ValueError, KeyError, OSError, TimeoutError, httpx.HTTPError) as exc:
            # Fixed local labels or HTTP codes only. No request dumps or upstream response texts.
            reason = str(exc) if type(exc) is ValueError else type(exc).__name__
            note(proof, stage, reason)
            raise SystemExit(2) from None
        finally:
            print('EVIDENCE', pack(work), flush=True)


def archive_app(data, job):
    """Replay the three captured GET resources at loopback for a Mac browser, with no worker or chat route."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    cid, jid = job['conversation_id'], job['id']

    @app.get('/api/conversations/{value}')
    def history(value: UUID):
        if str(value) != cid:
            raise HTTPException(404)
        return json.loads(data['conversation.json'])

    @app.get('/api/jobs/{value}')
    def saved(value: UUID, conversation_id: UUID):
        if (str(value),str(conversation_id)) != (jid,cid):
            raise HTTPException(404)
        return job

    @app.get('/api/jobs/{value}/structure')
    def pdb(value: UUID, conversation_id: UUID, download: bool = False):
        saved(value,conversation_id)
        kind = 'attachment' if download else 'inline'
        return Response(data['structure.pdb'], media_type='chemical/x-pdb', headers={
            'Content-Disposition': f'{kind}; filename="{job["download_name"]}"', 'Cache-Control':'no-store'})
    return app


async def mac(path, interactive):
    data = load(path)
    job = check_chat(data)
    check_gpu(data, job)
    async with loopback(archive_app(data,job)) as base:
        print('Mac · 第六轮已保存任务', base+'/?conversation='+job['conversation_id'], flush=True)
        if interactive:
            await asyncio.Event().wait()
        else:
            proof = path.with_name(path.stem+'-mac')
            proof.mkdir(exist_ok=True)
            await browser(base, proof, job, location='mac_archive', env=dict(os.environ))
            combined = {**data, **{p.name:p.read_bytes() for p in proof.iterdir()
                                  if p.name in ('browser.json','molstar.png','chat.png',job['download_name'])}}
            check_browser(combined, job, 'mac_archive')
            print('MOLSTAR + DOWNLOAD OK · Mac 归档复核', job['id'], proof)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for cmd in ('run','view'):
        p = subs.add_parser(cmd)
        p.add_argument('work', type=Path)
        p.add_argument('env_root', type=Path)
    for cmd in ('verify','mac-view','serve'):
        subs.add_parser(cmd).add_argument('archive', type=Path)
    args = parser.parse_args()
    if args.command == 'verify':
        verify(args.archive)
    elif args.command in ('mac-view','serve'):
        asyncio.run(mac(args.archive.resolve(), args.command == 'serve'))
    else:
        asyncio.run(colab(args.command, args.work.resolve(), args.env_root.resolve()))
