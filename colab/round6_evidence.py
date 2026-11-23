"""Portable, read-only checks for a single chat-triggered ubiquitin job."""

from hashlib import sha256
import json
import math
from pathlib import Path
import re
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import gemmi
from ubiquitin import (MODEL, OPTIONS, PACKAGE, SEED, SEQUENCE_SHA, TIMEOUT, UBIQUITIN,
                       check_resources, cli_args, cli_input, parse_prediction, require)
from app.config import FLASH

MESSAGE = '请用 Protenix 预测这条序列：\n' + UBIQUITIN
ORIGIN = 'round6_colab_chat_api'
HISTORICAL_RUN = '3c130b48-360c-43c0-8e67-2d78e0a90f3a'
PARAMS = dict(**OPTIONS, package_version=PACKAGE, seed=SEED, layernorm_type='torch', timeout_seconds=TIMEOUT)
FILES = {'request.json', 'reply.json', 'turn.json', 'conversation.json', 'job.json', 'provider.jsonl',
         'hardware.json', 'versions.json', 'resources.json', 'backend-versions.json', 'input.json',
         'protenix-input.json', 'cli-events.jsonl', 'events.jsonl', 'prediction.cif', 'structure.pdb',
         'structure-http.json', 'browser.json', 'chat.png', 'molstar.png', 'issue.json'}
# Pinned against the five objects verified in the returned round-5 T4 archive.
CACHE_SHA = {
    'checkpoint/protenix_mini_default_v0.5.0.pt': '3803340c5d9958c038e799ddd2b53b532db21855f261592ad455a5f003791f81',
    'common/components.cif': 'bb31ae5cf6c8bc669924313077cb4231ee5ffefd3a20118cd14f3ec89f8bb6a5',
    'common/components.cif.rdkit_mol.pkl': 'd1cfb71f5993a3ebea7c47877022d7f597bbfbaf86e28a4770e957da6c50cd35',
    'common/clusters-by-entity-40.txt': '1ab4af905e75b382eda8dec59917dc3608bee0729e36b9e71baf860bbe86850c',
    'common/obsolete_release_date.csv': 'a4f3f63ac5d7eebd78b07995cc669b9eccd6f5d8813c9492c9df02868893cf33',
}


def digest(blob):
    return sha256(blob).hexdigest()


def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.part')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_bytes())


def uid(value):
    require(isinstance(value, str) and str(UUID(value)) == value, 'UUID 格式不符')
    return value


def allowed(name):
    return name in FILES or bool(re.fullmatch(r'protenix-real-[0-9a-f-]{36}\.pdb', name))


def pack(work):
    proof = work / 'proof'
    rid = uid(read_json(proof / 'request.json')['request_id'])
    job = proof / 'job.json'
    label = uid(read_json(job)['id']) if job.is_file() else rid
    path = work / f'round6-protenix-{label}.zip'
    tmp = path.with_suffix('.zip.part')
    with ZipFile(tmp, 'w', ZIP_DEFLATED) as archive:
        hashes = {}
        for file in sorted(proof.iterdir()):
            if allowed(file.name) and file.is_file() and not file.is_symlink():
                blob = file.read_bytes()
                archive.writestr(file.name, blob)
                hashes[file.name] = digest(blob)
        archive.writestr('manifest.json', json.dumps(dict(origin=ORIGIN, request_id=rid, sha256=hashes), indent=2))
    tmp.replace(path)
    write_json(work / 'latest.json', {'file': path.name})
    return path


def load(path):
    with ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) <= len(FILES)+2 and 'manifest.json' in names
                and all(n == 'manifest.json' or allowed(n) for n in names), '第六轮归档的文件清单不符')
        require(all(0 < f.file_size <= 8_000_000 for f in archive.infolist()), '归档条目大小异常')
        data = {n: archive.read(n) for n in names if n != 'manifest.json'}
        manifest = json.loads(archive.read('manifest.json'))
    req = json.loads(data['request.json'])
    require(manifest == dict(origin=ORIGIN, request_id=uid(req['request_id']), sha256={n:digest(b) for n,b in data.items()})
            and req == {'request_id': req['request_id'], 'message': MESSAGE}, '请求或归档 SHA-256 不符')
    return data


def check_env(versions, hardware, resources):
    check_resources(resources)
    require({k:v['sha256'] for k,v in resources.items()} == CACHE_SHA, '权重或缓存 SHA-256 与第五轮不同')
    require('T4' in hardware['gpu'] and hardware['capability'] == '7.5' and 'T4' in versions['gpu']
            and versions['capability'] == [7, 5] and versions['python'] == '3.11.13'
            and versions['torch_cuda'] == '12.6' and versions['cli_version'] == PACKAGE, 'T4 环境记录不符')
    packages = {re.sub('[-_.]+', '-', k.lower()):v for k,v in versions['packages'].items()}
    for line in Path(__file__).with_name('requirements-linux-py311.lock').read_text().splitlines():
        name, version = line.split('==')
        require(packages.get(re.sub('[-_.]+', '-', name.lower()), '').split('+')[0] == version, 'GPU 依赖不符 · '+name)


def backend_pins():
    lock = Path(__file__).resolve().parents[1]/'backend/requirements.lock'
    return dict(line.split('==') for line in lock.read_text().splitlines() if line and not line.startswith('#'))


def check_chat(data):
    req, reply, turn, history, job = [json.loads(data[n+'.json']) for n in ('request','reply','turn','conversation','job')]
    rid, cid, jid = uid(req['request_id']), uid(reply['conversation_id']), uid(job['id'])
    require(len({rid, cid, jid, HISTORICAL_RUN}) == 4 and req['message'] == MESSAGE
            and turn['request_id'] == rid and turn['conversation_id'] == history['conversation_id'] == job['conversation_id'] == cid
            and reply['chat_mode'] == 'llm' and reply['outcome'] == 'job_submitted'
            and history['job_ids'] == reply['job_ids'] == [jid]
            and history['messages'] == [{'role':'user','text':MESSAGE}, {'role':'assistant','text':reply['assistant_message']}]
            and job['model'] == 'protenix' and job['mode'] == 'real' and job['fixture_source'] is None
            and job['length'] == 76 and job['model_version'] == MODEL and job['parameters'] == PARAMS and job['seed'] == SEED,
            '聊天、会话或任务不匹配')
    events = [json.loads(line) for line in data['provider.jsonl'].splitlines()]
    trace = turn['tools']
    require(2 <= len(events) <= 3 and all(e['url'] == 'https://api.deepseek.com/chat/completions'
            and e['http_status'] == 200 and e['requested_model'] == FLASH and e['completion_id']
            and e['response_model'] and e['user_message_matches'] for e in events)
            and events[-1]['finish_reason'] == 'stop', 'DeepSeek 往返记录不完整')
    calls = [call for e in events for call in e['calls']]
    submissions = [t for t in trace if t['result']['code'] == 'job_submitted']
    require(len(calls) == len(trace) and sum(t['reused'] is False for t in submissions) == 1, '工具提交次数不符')
    for call, t in zip(calls, trace):
        require(call['id'] and call['id'] == t['call_id'], '模型与数据库的工具调用 ID 不匹配')
        if t['result']['code'] != 'job_submitted':
            continue
        require(call == {'id':t['call_id'], 'name':'predict_structure','model':'protenix','sequence_sha256':SEQUENCE_SHA}
                and t['tool'] == call['name'] and t['result']['id'] == jid and t['result']['code'] == 'job_submitted'
                and t['result']['mode'] == 'real'
                and {'call_id':call['id'], 'job_id':jid, 'code':'job_submitted'} in events[-1]['sent_results'],
                'DeepSeek 工具调用、回传结果或任务编号不符')
    return job


def check_gpu(data, job):
    jid = job['id']
    job_input = json.loads(data['input.json'])
    require(all(job_input[k] == job[k] for k in ('id','conversation_id','model','mode','model_version','seed','parameters','created_at'))
            and job_input['sequence'] == UBIQUITIN and json.loads(data['protenix-input.json']) == cli_input(jid, UBIQUITIN),
            'worker 或官方 CLI 输入不符')
    check_env(*(json.loads(data[n+'.json']) for n in ('versions','hardware','resources')))
    require(json.loads(data['backend-versions.json']) == {'python':'3.11.13','packages':backend_pins()}, '后端依赖记录不符')
    cli = [json.loads(x) for x in data['cli-events.jsonl'].splitlines()]
    states = [json.loads(x) for x in data['events.jsonl'].splitlines()]
    require([s['status'] for s in states] == ['running','succeeded'] and all(s['error'] is None for s in states)
            and [e['stage'] for e in cli] == ['version_started','version_exited','cli_version','command','prediction_started','prediction_exited']
            and cli[1]['exit_code'] == cli[-1]['exit_code'] == 0 and cli[2]['package_version'] == PACKAGE
            and cli[3]['argv'] == ['protenix',*cli_args(PARAMS)] and cli[3]['layernorm_type'] == 'torch'
            and cli[-1]['diagnostic'] is None and cli[-1].get('cuda_selected') is True
            and job['created_at'] <= job['started_at'] <= cli[0]['utc'] <= cli[-1]['utc'] <= job['finished_at'],
            'CLI 执行或任务时间不符')
    source = parse_prediction(data['prediction.cif'], jid, UBIQUITIN)
    pdb = data['structure.pdb']
    require(job['status'] == 'succeeded' and job['result_available'] and job['error'] is None
            and job['download_name'] == f'protenix-real-{jid}.pdb' and job['sha256'] == digest(pdb)
            and pdb.splitlines()[:3] == [f'REMARK 950 JOB {jid}'.encode(), b'REMARK 950 MODE REAL',
                                         f'REMARK 950 {MODEL} SEED {SEED}'.encode()], 'PDB 归属或摘要不符')
    copy = gemmi.read_pdb_string(pdb)
    require(len(copy) == len(copy[0]) == 1 and copy[0][0].name == source[0][0].name
            and len(copy[0][0]) == 76, 'PDB 单链或残基数不符')
    for a,b in zip(source[0][0], copy[0][0]):
        require((a.name, str(a.seqid), len(a)) == (b.name, str(b.seqid), len(b)), 'PDB 残基不符')
        for p,q in zip(a,b):
            require((p.name,p.altloc,p.element) == (q.name,q.altloc,q.element) and p.pos.dist(q.pos) <= .001,
                    'mmCIF 和 PDB 的原子或坐标不符')
    return sum(len(r) for r in source[0][0])


def check_http(facts, job):
    for key, rec in facts.items():
        require(key in {'inline','attachment'} and rec == {
            'path':f"/api/jobs/{job['id']}/structure?conversation_id={job['conversation_id']}" +
                   ('&download=true' if key == 'attachment' else ''), 'status':200,
            'disposition':f'{key}; filename="{job["download_name"]}"', 'sha256':job['sha256']}, '结构 HTTP 响应不匹配')


def check_browser(data, job, location):
    record = json.loads(data['browser.json'])
    path = f"/api/jobs/{job['id']}/structure?conversation_id={job['conversation_id']}"
    require(record['conversation_id'] == job['conversation_id'] and record['job_id'] == job['id']
            and record['location'] == location and record['view_path'] == path
            and record['view_sha256'] == job['sha256'] and record['chat_requests'] == 0 and bool(record['browser'])
            and all(data[n].startswith(b'\x89PNG\r\n\x1a\n') for n in ('chat.png','molstar.png')), '画布归属或截图不符')
    before, rotated, zoomed = (record[n] for n in ('before','rotated','zoomed'))
    require(100 < before['area'] < 5300 and all(len(s['shape']) == 3 and all(math.isfinite(x) for x in s['shape'])
            for s in (before,rotated,zoomed)) and any(abs(x-y) > 4 for x,y in zip(before['shape'],rotated['shape']))
            and abs(zoomed['area']-rotated['area']) > rotated['area']*.10, '画布旋转或缩放证据不符')
    if 'download_name' in record:
        require(record['download_path'] == path+'&download=true' and record['download_name'] == job['download_name']
                and record['download_sha256'] == job['sha256']
                and data[job['download_name']] == data['structure.pdb'], '浏览器下载与任务不匹配')
    return record


def verify(path):
    data = load(path)
    if 'job.json' not in data:
        print('PARTIAL · 未取得已提交任务', read_json_value(data, 'issue.json'))
        return
    job = check_chat(data)
    print('CHAT OK', job['conversation_id'], 'JOB', job['id'])
    if job['status'] != 'succeeded':
        print('PARTIAL ·', job['status'], job['error'])
        return
    atoms = check_gpu(data, job)
    print('GPU OK · 1 chain · 76 aa ·', atoms, 'atoms · CIF', digest(data['prediction.cif']), 'PDB', job['sha256'])
    http = read_json_value(data, 'structure-http.json')
    check_http(http, job)
    print('结构 API', ', '.join(http) or '待验')
    if 'browser.json' in data:
        rec = check_browser(data, job, 'colab_backend')
        print('MOLSTAR OK · Colab · 浏览器下载', '通过' if rec.get('download_name') else '待验',
              '· 刷新', '通过' if rec.get('refresh') else '待验')
    else:
        print('PARTIAL · Mol* 和浏览器下载待验')


def read_json_value(data, name):
    return json.loads(data[name]) if name in data else {}
