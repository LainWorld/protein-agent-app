"""Exercise the real queue, file validator and public routes; only DeepSeek is doubled."""

import asyncio
from contextlib import asynccontextmanager, closing
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import sys
import sqlite3
from urllib.parse import urlencode
from uuid import uuid4

import gemmi
import httpx
import pytest

from app.adapters.mock import FIXTURE, FIXTURE_SHA, MockAdapter
from app.adapters.protenix import MODEL as MINI, PACKAGE as PROTENIX_PACKAGE, cif_path, cli_input
from app.adapters.esmfold2 import ATOM37, FOLD_URL
from app.config import ESMFOLD2_FAST, Settings
from app.main import create_app
from app.structures import InvalidOutput, verified_pdb

UBQ = 'MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@asynccontextmanager
async def stack(tmp, *, fold_upstream=None, **opts):
    conf = replace(Settings('deepseek','https://api.deepseek.com','test','test',tmp/'app.sqlite3', mock_delay=0), **opts)
    frames = []
    calls = []
    def upstream(request):
        if request.url.host in {'biohub.ai', 'api.openprotein.ai'}:
            assert fold_upstream is not None, 'unexpected fold request'
            return fold_upstream(request)
        calls.append(json.loads(request.content))
        msg = frames.pop(0)
        return httpx.Response(200, json={'choices':[{'message':msg,'finish_reason':'tool_calls' if 'tool_calls' in msg else 'stop'}]})
    app = create_app(conf, httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
        yield app, client, frames, calls


async def submit(client, frames, model, cid=None):
    frames.extend([{'role':'assistant','tool_calls':[{'id':'call_'+model,'type':'function','function':{
        'name':'predict_structure','arguments':json.dumps({'sequence':UBQ,'model':model})}}]},
        {'role':'assistant','content':'{"act":"result","lang":"en"}'}])
    response = await client.post('/api/chat',json={'message':f'Use {model}. Sequence: {UBQ}', 'conversation_id':cid,'request_id':str(uuid4())})
    assert response.status_code==200 and response.json()['outcome']=='job_submitted'
    return response.json()['conversation_id'], response.json()['job_ids'][0]


def route(cid, jid, file=False):
    return f'/api/jobs/{jid}' + ('/structure' if file else '') + '?' + urlencode({'conversation_id':cid})


async def terminal(client,cid,jid):
    async with asyncio.timeout(3):
        while True:
            j=(await client.get(route(cid,jid))).json()
            if j['status'] in {'succeeded','failed'}: return j
            await asyncio.sleep(.005)


async def test_two_routes_use_one_worker_and_isolated_validated_downloads(tmp_path, monkeypatch):
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest()==FIXTURE_SHA
    entered, release = asyncio.Event(), asyncio.Event()
    active, peak = 0, 0
    order = []
    real = MockAdapter.predict
    async def gate(self, seq, directory, params):
        nonlocal active, peak
        active+=1; peak=max(active,peak); order.append(self.model); entered.set()
        try:
            await release.wait()
            return await real(self, seq, directory, params)
        finally: active-=1
    monkeypatch.setattr(MockAdapter,'predict',gate)
    async with stack(tmp_path) as (_,c,frames,calls):
        cid, a = await submit(c,frames,'esmfold2')
        await asyncio.wait_for(entered.wait(),1)
        _, b = await submit(c,frames,'protenix',cid)
        assert a!=b and order==['esmfold2']
        for jid,state in [(a,'running'),(b,'queued')]:
            j=(await c.get(route(cid,jid))).json()
            assert j['status']==state and not j['result_available'] and not j['download_name']
            assert (await c.get(route(cid,jid,True))).status_code==409
        release.set()
        hashes=[]
        for jid,model in [(a,'esmfold2'),(b,'protenix')]:
            j=await terminal(c,cid,jid)
            assert j['status']=='succeeded' and j['mode']=='mock' and j['model']==model and j['length']==76
            assert j['result_available'] and j['created_at']<=j['started_at']<=j['finished_at']
            assert j['parameters']['fixture_sha256']==FIXTURE_SHA and j['fixture_source'].endswith('/1UBQ') and j['seed'] is None
            inline=await c.get(route(cid,jid,True))
            download=await c.get(route(cid,jid,True)+'&download=true')
            assert inline.content==download.content and inline.status_code==download.status_code==200
            assert f'attachment; filename="{model}-mock-{jid}.pdb"'==download.headers['content-disposition']
            assert jid.encode() in download.content and b'NOT A PREDICTION' in download.content
            assert hashlib.sha256(download.content).hexdigest()==j['sha256']; hashes.append(j['sha256'])
            chain=gemmi.read_pdb_string(download.content)[0]['A']
            assert ''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in chain if r.het_flag=='A')==UBQ
            directory=tmp_path/'jobs'/jid
            assert json.loads((directory/'input.json').read_text())['sequence']==UBQ
            assert [json.loads(line)['status'] for line in (directory/'events.jsonl').read_text().splitlines()]==['running','succeeded']
            assert (await c.get(route(uuid4(),jid,True))).status_code==404
        assert peak==1 and order==['esmfold2','protenix'] and hashes[0]!=hashes[1]
        assert len(calls)==4  # polling and downloads never call LLM
        assert (await c.get('/api/conversations/'+cid)).json()['job_ids']==[a,b]


@pytest.mark.parametrize(('failure','expected'), [('raise','execution_error'),('timeout','timeout'),('missing','invalid_output'),
    ('empty','invalid_output'),('garbled','invalid_output'),('water','invalid_output'),('wrong-job','invalid_output')])
async def test_failures_never_expose_structure(tmp_path, monkeypatch, failure, expected):
    async def broken(self, seq, directory, params):
        path=directory/'structure.pdb'
        if failure=='raise': raise OSError('private path/credentials must not leak')
        if failure=='timeout': await asyncio.sleep(3)
        if failure=='empty': path.touch()
        if failure in ('water','garbled'):
            records = [l for l in FIXTURE.read_bytes().splitlines() if l.startswith(b'HETATM')] if failure=='water' else [b'ATOM      1  CA  ALA A   1      broken']
            path.write_bytes(f'REMARK 950 JOB {directory.name}\n'.encode()+b'\n'.join(records))
        if failure=='wrong-job': return FIXTURE
        return path
    monkeypatch.setattr(MockAdapter,'predict',broken)
    async with stack(tmp_path, job_timeout=.04) as (_,c,frames,_):
        cid,jid=await submit(c,frames,'protenix')
        j=await terminal(c,cid,jid)
        assert j['status']=='failed' and j['error']==expected and j['error_message']
        assert j['sha256'] is None and not j['result_available'] and not j['download_name']
        assert (await c.get(route(cid,jid,True)+'&download=true')).status_code==409
        assert 'private path' not in json.dumps(j)


@pytest.mark.parametrize('variant',['replace','delete','symlink'])
async def test_tampered_success_revoked_on_read(tmp_path,variant):
    async with stack(tmp_path) as (_,c,frames,_):
        cid,jid=await submit(c,frames,'esmfold2')
        j=await terminal(c,cid,jid); assert j['status']=='succeeded'
        p=tmp_path/'jobs'/jid/'structure.pdb'
        if variant=='replace': p.write_bytes(p.read_bytes().replace(b'HEADER', b'REMARK',1))
        else:
            p.unlink()
            if variant=='symlink': p.symlink_to(FIXTURE)
        assert (await c.get(route(cid,jid,True))).status_code==409
        j=(await c.get(route(cid,jid))).json()
        assert j['status']=='failed' and j['error']=='invalid_output' and not j['result_available']


async def test_restart_fails_unfinished_jobs_does_not_resubmit(tmp_path):
    async with stack(tmp_path, mock_delay=10) as (_,c,frames,_):
        cid,a=await submit(c,frames,'esmfold2')
        _,b=await submit(c,frames,'protenix',cid)
    # Simulate records left by an ungraceful kill (not just orderly shutdown).
    with closing(sqlite3.connect(tmp_path/'app.sqlite3')) as db,db:
        db.execute("UPDATE jobs SET status='running',error=NULL,finished_at=NULL WHERE id=?",(a,))
        db.execute("UPDATE jobs SET status='queued',error=NULL,finished_at=NULL WHERE id=?",(b,))
    async with stack(tmp_path) as (_,c,_,calls):
        for jid in (a,b):
            j=(await c.get(route(cid,jid))).json()
            assert j['status']=='failed' and j['error']=='interrupted' and not j['result_available']
        assert (await c.get('/api/conversations/'+cid)).json()['job_ids']==[a,b] and not calls


async def test_misplaced_file_with_valid_coordinates_is_not_a_job_output(tmp_path):
    with pytest.raises(InvalidOutput):
        verified_pdb(tmp_path, FIXTURE, mock=True)


def ubiquitin_fold_reply():
    # Experimental coordinates stand in for an HTTP response in the temp DB only.
    rows = []
    chain = gemmi.read_pdb(str(FIXTURE))[0]['A']
    for residue in chain:
        if residue.het_flag != 'A':
            continue
        atoms = {a.name: list(a.pos) for a in residue}
        rows.append([atoms.get(name, [None, None, None]) for name in ATOM37])
    return {'model': ESMFOLD2_FAST, 'sequence': UBQ, 'coordinates': rows}


@pytest.mark.parametrize('envelope', [False, True])
async def test_real_adapter_through_chat_download_and_recovery(tmp_path, envelope):
    requests = []
    def fold(req):
        requests.append(req)
        data = ubiquitin_fold_reply()
        return httpx.Response(200, json={'data': data} if envelope else data)

    async with stack(tmp_path, esmfold2_mode='real', esmfold2_key='unit-test-biohub', fold_upstream=fold) as (_, c, frames, llm):
        cid, jid = await submit(c, frames, 'esmfold2')
        job = await terminal(c, cid, jid)
        assert job['status'] == 'succeeded' and job['mode'] == 'real' and job['result_available']
        assert job['model_version'] == ESMFOLD2_FAST and job['length'] == 76 and job['seed'] is None
        assert job['fixture_source'] is None and 'fixture_id' not in job['parameters']
        assert len(requests) == 1 and len(llm) == 2
        req = requests[0]
        assert req.method == 'POST' and str(req.url) == FOLD_URL
        assert req.headers['Authorization'] == 'Bearer unit-test-biohub'
        assert req.headers['Accept'] == 'application/json' and req.headers['X-Disable-Cache'] == 'true'
        assert json.loads(req.content) == {'sequence': UBQ, 'model': ESMFOLD2_FAST, 'msa': None}
        assert json.loads(llm[-1]['messages'][-1]['content'])['mode'] == 'real'
        history = (await c.get('/api/conversations/'+cid)).json()
        assert history['job_ids'] == [jid] and 'Real' in history['messages'][-1]['text']
        assert 'Mock' not in history['messages'][-1]['text']
        url = route(cid, jid, True)
        inline, download = await c.get(url), await c.get(url+'&download=true')
        assert inline.content == download.content and job['sha256'] == hashlib.sha256(download.content).hexdigest()
        assert job['download_name'] == f'esmfold2-real-{jid}.pdb'
        assert download.headers['content-disposition'] == f'attachment; filename="{job["download_name"]}"'
        assert b'MOCK' not in download.content and jid.encode() in download.content
        assert (await c.get(route(uuid4(), jid, True))).status_code == 404
        pdb = gemmi.read_pdb_string(download.content)
        chain = pdb[0]['A']
        assert len(pdb) == len(pdb[0]) == 1
        assert ''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in chain) == UBQ
        # Check real atom identities/coordinates with an independent PDB reader and source.
        reference = gemmi.read_pdb(str(FIXTURE))[0]['A']
        for res, original in zip(chain, reference):
            assert len(res) == len(original)
            for atom in original:
                stored = res.find_atom(atom.name, '*')
                assert stored.element == atom.element and stored.pos.dist(atom.pos) < .001
        directory = tmp_path/'jobs'/jid
        assert json.loads((directory/'input.json').read_text())['parameters']['fold_options'] == {'model': ESMFOLD2_FAST, 'msa': None}
        assert all(b'unit-test-biohub' not in f.read_bytes() for f in [*directory.iterdir(),tmp_path/'app.sqlite3'])
        assert 'unit-test-biohub' not in repr(job) and len(requests) == 1
    # Existing results stay attached to their original mode after the server changes back to Mock.
    async with stack(tmp_path) as (_, c, _, calls):
        restored = (await c.get(route(cid, jid))).json()
        assert restored['mode'] == 'real' and restored['sha256'] == job['sha256'] and not calls


@pytest.mark.parametrize(('case','expected'), [
    (401,'biohub_auth'), (402,'biohub_credits'), (403,'biohub_access'), (422,'biohub_input'),
    (429,'biohub_rate_limit'), (451,'biohub_region'), (503,'biohub_upstream'), (307,'biohub_upstream'),
    ('connect','biohub_connection'), ('timeout','timeout'), ('HTML','invalid_output'), ('bad_json','invalid_output'),
    ('wrong_model','invalid_output'), ('wrong_sequence','invalid_output'), ('length','invalid_output'),
    ('missing_CA','invalid_output'), ('short_row','invalid_output'), ('partial_xyz','invalid_output'),
])
async def test_biohub_failures_make_one_request_and_no_result(tmp_path, case, expected):
    requests = []
    def fold(req):
        requests.append(req)
        if isinstance(case, int):
            return httpx.Response(case, text='private-provider-error', headers={'Location':'https://example.invalid'})
        if case == 'connect':
            raise httpx.ConnectError('private-provider-error')
        if case == 'timeout':
            raise httpx.ReadTimeout('private-provider-error')
        if case in ('HTML','bad_json'):
            return httpx.Response(200, text='private-provider-error', headers={
                'Content-Type': 'text/html' if case == 'HTML' else 'application/json'})
        data = ubiquitin_fold_reply()
        if case == 'wrong_model': data['model'] = 'different-model'
        if case == 'wrong_sequence': data['sequence'] = UBQ[::-1]
        if case == 'length': data['coordinates'].pop()
        if case == 'short_row': data['coordinates'][0].pop()
        if case == 'missing_CA': data['coordinates'][0][1] = [None]*3
        if case == 'partial_xyz': data['coordinates'][0][0] = [1, None, 3]
        return httpx.Response(200, json=data)

    async with stack(tmp_path, esmfold2_mode='real', esmfold2_key='unit-test-biohub', fold_upstream=fold) as (_, c, frames, _):
        cid, jid = await submit(c, frames, 'esmfold2')
        job = await terminal(c, cid, jid)
        assert job['status'] == 'failed' and job['mode'] == 'real' and job['error'] == expected
        assert not job['result_available'] and job['download_name'] is None and job['sha256'] is None
        assert (await c.get(route(cid,jid,True)+'&download=true')).status_code == 409
        assert len(requests) == 1 and not (tmp_path/'jobs'/jid/'structure.pdb').exists()
        assert b'private-provider-error' not in (tmp_path/'app.sqlite3').read_bytes()


@pytest.mark.parametrize('config', [{}, {'esmfold2_key':'test', 'esmfold2_url':'https://example.invalid'},
                                    {'esmfold2_key':'test', 'esmfold2_model':'esmfold_v1'}])
async def test_unconfigured_real_never_submits_or_sends_token(tmp_path, config):
    async with stack(tmp_path, esmfold2_mode='real', protenix_mode='real', **config) as (_, c, frames, _):
        h = (await c.get('/api/health')).json()
        assert h['prediction_modes']['esmfold2'] == 'real' and not h['prediction_enabled']
        assert h['prediction_configured'] == {'esmfold2': False, 'protenix': False}
        frames.extend([{'role':'assistant','tool_calls':[{'id':'call1','type':'function','function':{
            'name':'predict_structure','arguments':json.dumps({'sequence':UBQ,'model':'esmfold2'})}}]},
            {'role':'assistant','content':'{"act":"result","lang":"en"}'}])
        reply = (await c.post('/api/chat',json={'message':f'Use ESMFold2. Sequence: {UBQ}'})).json()
        assert reply['outcome'] == 'biohub_config' and not reply['job_ids']
        assert not (await c.get('/api/conversations/'+reply['conversation_id'])).json()['job_ids']


def install_cli_double(tmp, case):
    executable = tmp / 'isolated env' / 'protenix'
    executable.parent.mkdir()
    double = executable.with_name('test-double.py')
    shutil.copyfile(Path(__file__).with_name('protenix_cli_double.py'), double)
    executable.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(double))} "$@"\n')
    executable.chmod(0o700)
    (executable.parent / 'case').write_text(case)
    (executable.parent / 'sequence').write_text(UBQ)
    reference = gemmi.read_structure(str(FIXTURE))
    reference.remove_waters()
    if case == 'wrong_sequence':
        reference[0][0][0].name = 'ALA'
    if case == 'missing_ca':
        reference[0][0][0].remove_atom('CA', '*')
    if case == 'nan':
        reference[0][0][0][0].pos.x = float('nan')
    block = reference.make_mmcif_document().sole_block()
    block.name = 'RUNID_sample_0_predicted_by_protenix'
    block.set_pair('_entry.id', 'RUNID')
    (executable.parent / 'reference.cif').write_text(block.as_string())
    return {'protenix_mode': 'real', 'protenix_executable': str(executable), 'protenix_root': tmp / 'cache'}


async def test_protenix_chat_cli_download_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_API_KEY', 'backend-only-test-value')
    monkeypatch.setenv('ESMFOLD2_API_KEY', 'backend-only-test-value')
    async with stack(tmp_path, **install_cli_double(tmp_path, 'success')) as (app, c, frames, calls):
        assert (await c.get('/api/health')).json()['prediction_configured']['protenix']
        cid, jid = await submit(c, frames, 'protenix')
        job = await terminal(c, cid, jid)
        assert job['status'] == 'succeeded' and job['result_available'] and job['mode'] == 'real'
        assert job['length'] == 76 and job['model_version'] == MINI and job['seed'] == 101
        assert job['parameters']['package_version'] == PROTENIX_PACKAGE and job['fixture_source'] is None
        assert ('protenix', 'mock') not in app.state.jobs.adapters
        directory = tmp_path / 'jobs' / jid
        assert json.loads((directory / 'protenix-input.json').read_text()) == cli_input(jid, UBQ)
        assert json.loads((directory / 'input.json').read_text())['seed'] == 101
        assert gemmi.cif.read_file(str(cif_path(directory, 101))).sole_block().find_value('_entry.id') == jid
        url = route(cid, jid, True)
        inline, download = await c.get(url), await c.get(url + '&download=true')
        assert inline.content == download.content and (await c.get(route(uuid4(), jid, True))).status_code == 404
        assert hashlib.sha256(download.content).hexdigest() == job['sha256']
        assert job['download_name'] == f'protenix-real-{jid}.pdb'
        assert download.headers['content-disposition'] == f'attachment; filename="{job["download_name"]}"'
        chain = gemmi.read_pdb_string(inline.content)[0][0]
        assert ''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in chain) == UBQ
        assert all(a.pos.dist(b.pos) < .001 for r, s in zip(chain, gemmi.read_pdb(str(FIXTURE))[0][0])
                   for a, b in zip(r, s))
        saved = (await c.get('/api/conversations/' + cid)).json()
        assert 'Protenix CLI' in saved['messages'][-1]['text'] and 'Biohub' not in saved['messages'][-1]['text']
        log = (directory / 'cli-events.jsonl').read_text()
        assert len(calls) == 2 and log.count('prediction_started') == 1 and json.loads(log.splitlines()[-1])['exit_code'] == 0
        assert 'upstream-private-string' not in log and 'backend-only-test-value' not in log
    async with stack(tmp_path) as (_, c, _, calls):
        assert (await c.get(route(cid, jid))).json()['sha256'] == job['sha256'] and not calls


@pytest.mark.parametrize(('case','error'), [
    ('nonzero', 'protenix_execution'), ('version', 'protenix_version'), ('oom', 'protenix_oom'),
    ('reported', 'protenix_execution'), ('missing', 'invalid_output'), ('empty','invalid_output'),
    ('corrupt', 'invalid_output'), ('wrong_seed', 'invalid_output'), ('wrong_job', 'invalid_output'),
    ('wrong_block', 'invalid_output'), ('wrong_sequence', 'invalid_output'), ('missing_ca', 'invalid_output'),
    ('nan', 'invalid_output'), ('symlink', 'invalid_output'), ('timeout', 'timeout'),
])
async def test_protenix_cli_failures(tmp_path, case, error):
    async with stack(tmp_path, **install_cli_double(tmp_path, case), job_timeout=1.5 if case == 'timeout' else 3) as (app, c, frames, _):
        cid, jid = await submit(c, frames, 'protenix')
        job = await terminal(c, cid, jid)
        assert job['status'] == 'failed' and job['error'] == error and job['error_message']
        assert not job['result_available'] and job['sha256'] is None and job['download_name'] is None
        assert job['mode'] == 'real' and ('protenix', 'mock') not in app.state.jobs.adapters
        assert (await c.get(route(cid, jid, True) + '&download=true')).status_code == 409
        directory = tmp_path / 'jobs' / jid
        assert not (directory / 'structure.pdb').exists()
        events = (directory / 'cli-events.jsonl').read_text()
        assert 'upstream-private-string' not in events
        if case == 'version':
            assert 'prediction_started' not in events
        if case == 'timeout':
            assert (directory / 'spawned').exists() and 'prediction_interrupted' in events
            (directory / 'release-child').touch()
            await asyncio.sleep(.35)
            assert not (directory / 'leaked-child').exists()
