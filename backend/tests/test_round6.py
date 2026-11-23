"""Round-six acceptance mechanics. All provider, CUDA and coordinate evidence here is temporary test data."""

import base64
from contextlib import closing
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from test_jobs import install_cli_double

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'colab')]
import build_round6_colab as build
import round6 as run
import round6_evidence as ev
from resources import OBJECTS, ORIGIN


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def test_notebook_has_only_deployed_files_and_preserves_fifth_round():
    original = build.FIFTH.read_bytes()
    assert ev.digest(original) == '54bb02384ef17c5aabc3c840e7c9a127e8cb27b8fdfd4091870d2e5c1bc13ccd'
    nb = json.loads(build.NOTEBOOK.read_bytes())
    old = {c['id']:c for c in json.loads(original)['cells']}
    stages = {c['id']:c for c in nb['cells'] if c['cell_type']=='code'}
    assert list(stages) == ['gpu','install','assets','app','viewer-setup','chat','download']
    for name in ('gpu','install','assets'):
        assert stages[name] == old[name]
    for name,c in stages.items():
        assert c['outputs'] == [] and c['execution_count'] is None
        compile(''.join(c['source']),name,'exec')
    source = ''.join(stages['app']['source'])
    raw = base64.b64decode(re.search("b64decode\\('''(.*?)'''\\)",source,re.S)[1])
    assert ev.digest(raw) in source
    with ZipFile(BytesIO(raw)) as z:
        # Pytest also runs in a fresh checkout before the frontend is built.
        project_names = set(build.SUPPORT) | {'backend/app/'+s+'.py' for s in build.APP}
        assets = set(z.namelist()) - project_names
        assert len(assets) == 3 and all(re.fullmatch(r'frontend/dist/assets/(index|StructureViewer)-[\w-]+\.(js|css)', n) for n in assets)
        for name in project_names - {'frontend/dist/index.html'}:
            assert z.read(name) == (ROOT/name).read_bytes()
        assert all(not any(p in n for p in ('.env','1ubq','sqlite','__pycache__','examples/')) for n in z.namelist())
    if (ROOT/'frontend/dist/index.html').exists():
        assert nb == build.notebook()
    assert 'DEEPSEEK_API_KEY' in ''.join(stages['chat']['source'])
    assert 'userdata' not in ''.join(stages['viewer-setup']['source'])
    assert ev.UBIQUITIN in (ROOT/'examples/fixtures/README.md').read_text()


def setup_run(tmp):
    proof = tmp/'proof'
    proof.mkdir()
    ev.write_json(proof/'request.json', dict(message=ev.MESSAGE,request_id=str(uuid4())))
    packages = dict(s.split('==') for s in (ROOT/'colab/requirements-linux-py311.lock').read_text().splitlines())
    ev.write_json(proof/'hardware.json',dict(gpu='T4 offline double',capability='7.5'))
    ev.write_json(proof/'versions.json',dict(python='3.11.13',gpu='T4 offline double',capability=[7,5],torch_cuda='12.6',
                                             cli_version=ev.PACKAGE,packages=packages))
    ev.write_json(proof/'backend-versions.json',dict(python='3.11.13',packages=ev.backend_pins()))
    ev.write_json(proof/'resources.json',{rel:dict(bytes=size,crc64ecma=str(crc),url=ORIGIN+rel,sha256=ev.CACHE_SHA[rel])
                                          for rel,size,crc in OBJECTS.values()})
    config = Settings('deepseek',run.DEEPSEEK,ev.FLASH,'test-only-secret-never-export',tmp/'data/app.sqlite3',
                      esmfold2_mode='real',job_timeout=ev.TIMEOUT, **install_cli_double(tmp,'success'))
    calls = []
    def upstream(request):
        messages = json.loads(request.content)['messages']
        calls.append(messages[-1]['role'])
        if calls[-1] == 'user':
            assert messages[-1]['content'] == ev.MESSAGE
            args = json.dumps(dict(model='protenix',sequence=ev.UBIQUITIN))
            reply = dict(role='assistant',tool_calls=[dict(type='function',id='call_offline',
                                                          function=dict(name='predict_structure',arguments=args))])
        else:
            assert messages[-1]['tool_call_id'] == 'call_offline'
            reply = dict(role='assistant',content='{"act":"result","lang":"zh"}')
        return httpx.Response(200, json=dict(id='offline-'+str(len(calls)),model='offline-test-double',choices=[
            dict(finish_reason='tool_calls' if 'tool_calls' in reply else 'stop',message=reply)]))
    return create_app(config,httpx.MockTransport(upstream)), calls


@pytest.mark.anyio
async def test_capture_and_retry_after_structure_http_failure(tmp_path, monkeypatch):
    app,calls = setup_run(tmp_path)
    requests = []
    async def track(request):
        requests.append((request.method,request.url.path))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url='http://test', event_hooks={'request':[track]}) as client:
        async def fail_download(*args):
            raise ValueError('offline simulated HTTP failure')
        with monkeypatch.context() as m:
            m.setattr(run,'read_structure',fail_download)
            with pytest.raises(ValueError, match='simulated HTTP'):
                await run.capture(app,client,tmp_path)
        path = tmp_path/ev.read_json(tmp_path/'latest.json')['file']
        data = ev.load(path)
        job = ev.check_chat(data)
        assert ev.check_gpu(data,job) > 76 and 'structure-http.json' not in data
        await run.capture(app,client,tmp_path,allow_submit=False)
        data = ev.load(ev.pack(tmp_path))
        ev.check_http(json.loads(data['structure-http.json']), job)
        assert json.loads(data['job.json']) == job and calls == ['user','tool']
        assert requests.count(('POST','/api/chat')) == 1
        with closing(app.state.store.connect()) as db:
            assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 1
        assert [json.loads(x)['stage'] for x in data['cli-events.jsonl'].splitlines()].count('prediction_started') == 1
        assert all(b'test-only-secret' not in b and b'upstream-private-string' not in b and b'Authorization' not in b for b in data.values())
        # These are genuine evidence inconsistencies even if someone recomputes the archive manifest.
        wrong = json.loads(data['turn.json'])
        wrong['tools'][0]['result']['id'] = str(uuid4())
        with pytest.raises(ValueError):
            ev.check_chat({**data,'turn.json':json.dumps(wrong).encode()})
        with pytest.raises(ValueError):
            ev.check_gpu({**data,'prediction.cif':data['prediction.cif'].replace(job['id'].encode(),str(uuid4()).encode())},job)
        with pytest.raises(ValueError):
            ev.check_gpu({**data,'structure.pdb':data['structure.pdb']+b'\n'},job)
        with pytest.raises(ValueError):
            ev.check_http({'inline':{'sha256':'0'*64}},job)
        pic = b'\x89PNG\r\n\x1a\n'
        url = f"/api/jobs/{job['id']}/structure?conversation_id={job['conversation_id']}"
        record = dict(conversation_id=job['conversation_id'],job_id=job['id'],browser='offline',before=dict(area=200,shape=[1,2,3]),
                      rotated=dict(area=210,shape=[1,2,12]),zoomed=dict(area=330,shape=[1,2,12]),view_sha256=job['sha256'],chat_requests=0,
                      location='offline_backend',view_path=url,download_path=url+'&download=true',
                      download_name=job['download_name'],download_sha256=job['sha256'])
        with pytest.raises(ValueError):
            ev.check_browser({**data,'browser.json':json.dumps(record).encode(),'chat.png':pic,'molstar.png':pic,
                              job['download_name']:b'wrong download'},job,'offline_backend')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=run.archive_app(data,job)),base_url='http://mac') as local:
        route = '/api/jobs/'+job['id']+'/structure?conversation_id='
        assert (await local.get(route+str(uuid4()))).status_code == 404
        assert (await local.get(route+job['conversation_id']+'&download=true')).content == data['structure.pdb']
        assert (await local.post('/api/chat',json={})).status_code in (404,405)


def test_reject_wrong_archive_and_concurrent_backend(tmp_path):
    with run.exclusive(tmp_path), pytest.raises(ValueError,match='已有验收进程'), run.exclusive(tmp_path):
        pass
    invalid = tmp_path/'standalone.zip'
    with ZipFile(invalid,'w') as z:
        z.writestr('run.json','{"origin":"standalone_colab"}')
        z.writestr('manifest.json','{}')
    with pytest.raises(ValueError,match='第六轮'):
        ev.load(invalid)


def test_notebook_secret_travels_only_on_stdin_and_committed_case_skips_secrets(tmp_path, monkeypatch, capsys):
    # Execute the actual notebook cell with a local Colab API stub and a real Python subprocess.
    nb = json.loads(build.NOTEBOOK.read_bytes())
    source = ''.join(next(c for c in nb['cells'] if c['id']=='chat')['source'])
    driver = tmp_path/'inspect-pipe.py'
    driver.write_text("""import os,sys
from pathlib import Path
secret = sys.stdin.read().strip()
assert 'offline-pipe-value' not in str(sys.argv) and 'offline-pipe-value' not in str(dict(os.environ))
assert secret == ('offline-pipe-value' if sys.argv[1]=='run' else '')
print('stage',sys.argv[1])
""")
    calls = []
    def secret(name):
        calls.append(name)
        return 'offline-pipe-value'
    colab = ModuleType('google.colab')
    colab.userdata = SimpleNamespace(get=secret)
    monkeypatch.setitem(sys.modules,'google.colab',colab)
    world = dict(work=tmp_path, root=tmp_path, project=tmp_path, app_py=sys.executable, driver=driver,
                 env={'PATH':os.defpath}, subprocess=subprocess, os=os)
    exec(source,world)
    (tmp_path/'data').mkdir()
    with closing(sqlite3.connect(tmp_path/'data/app.sqlite3')) as db, db:
        db.execute('CREATE TABLE turns (request_id TEXT, user_text TEXT)')
        db.execute('INSERT INTO turns VALUES (?,?)',(str(uuid4()),ev.MESSAGE))
    exec(source,world)
    assert calls == ['DEEPSEEK_API_KEY'] and capsys.readouterr().out.splitlines() == ['stage run','stage view']


@pytest.mark.anyio
async def test_no_resubmit_on_missing_turn_and_auth_failure_exports_diagnostics(tmp_path):
    original,calls = setup_run(tmp_path)
    async with original.router.lifespan_context(original):
        config = original.state.config
    app = create_app(config,httpx.MockTransport(lambda r:httpx.Response(401,content=b'private-provider-message')))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        with pytest.raises(ValueError,match='只读'):
            await run.capture(app,c,tmp_path,allow_submit=False)
        await run.capture(app,c,tmp_path)
    data = ev.load(ev.pack(tmp_path))
    assert json.loads(data['issue.json'])['reason'] == 'HTTP 503 · llm_auth'
    assert json.loads(data['provider.jsonl'])['http_status'] == 401
    assert 'job.json' not in data and not calls and all(b'private-provider-message' not in b for b in data.values())
    assert not list((tmp_path/'data/jobs').iterdir())
