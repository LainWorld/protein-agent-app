"""Offline integration tests: real ASGI + SQLite + provider wire format; fake HTTP upstream."""

from contextlib import asynccontextmanager, closing
from dataclasses import replace
import json
import sqlite3
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def plan(act='help', lang='en', **kw):
    return {'role': 'assistant', 'content': json.dumps(dict(act=act, lang=lang, **kw))}


def tool(name='predict_structure', cid='call_1', **args):
    return {'role': 'assistant', 'content': None, 'tool_calls': [{'type': 'function', 'id': cid,
            'function': {'name': name, 'arguments': json.dumps(args)}}]}


class Upstream:
    def __init__(self):
        self.queue, self.sent = [], []

    def __call__(self, req):
        assert req.url.host == 'api.deepseek.com' and req.url.path == '/chat/completions'
        body = json.loads(req.content)
        assert body['thinking'] == {'type': 'disabled'}
        assert [t['function']['name'] for t in body['tools']] == ['predict_structure', 'get_job_status']
        self.sent.append(body)
        msg = self.queue.pop(0)
        if isinstance(msg, httpx.Response):
            return msg
        return httpx.Response(200, json={'choices': [{'message': msg, 'finish_reason': 'tool_calls' if 'tool_calls' in msg else 'stop'}]})


@asynccontextmanager
async def session(conf, upstream):
    app = create_app(conf, httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as client:
        yield client


@pytest.fixture
def config(tmp_path):
    return Settings('deepseek', 'https://api.deepseek.com', 'deepseek-flash', 'offline-placeholder', tmp_path/'app.sqlite3')


@pytest.fixture
def up():
    return Upstream()


@pytest.fixture
async def client(config, up):
    async with session(config, up) as c:
        yield c


async def chat(c, text, conversation=None, rid=None):
    return await c.post('/api/chat', json={'message': text, 'conversation_id': conversation, 'request_id': rid})


async def test_health_and_unknown_conversation_make_no_llm_call(client, up):
    assert (await client.get('/api/health')).json() == {'status':'ok','chat_mode':'llm','llm_configured':True,
        'prediction_enabled':True,'prediction_modes':{'esmfold2':'mock','protenix':'mock'},
        'prediction_configured':{'esmfold2':True,'protenix':True}}
    unknown = str(uuid4())
    assert (await client.get('/api/conversations/'+unknown)).status_code == 404
    assert (await chat(client, 'Hi', unknown)).status_code == 404
    assert not up.sent


@pytest.mark.parametrize('payload', [{}, {'message':''}, {'message':' \n '}, {'message':4}, {'message':'a'*4001},
    {'message':'hi','conversation_id':'broken'}, {'message':'hi','request_id':'broken'}, {'message':'hi','extra':True}])
async def test_invalid_chat_never_calls_provider(client, up, payload):
    r = await client.post('/api/chat', json=payload)
    assert r.status_code == 422 and r.json()['error']['code'] == 'invalid_request' and not up.sent


async def test_invalid_json(client):
    assert (await client.post('/api/chat', content='{', headers={'Content-Type':'application/json'})).status_code == 422


async def test_pending_sequence_survives_restart_and_can_switch_models(config, up):
    args = {'sequence':'ACDE','model':'esmfold2'}
    # The real model can guess a default even though no model was specified.
    up.queue += [tool(**args), plan('result','zh')]
    async with session(config, up) as c:
        first = (await chat(c, '请预测这条序列：\naC dE')).json()
        cid = first['conversation_id']; UUID(cid)
        assert first['outcome'] == 'ask_model' and '4 aa' in first['assistant_message'] and not first['job_ids']
        paired = up.sent[-1]['messages'][-1]
        assert paired['role'] == 'tool' and paired['tool_call_id'] == 'call_1' and json.loads(paired['content'])['code'] == 'ask_model'
    async with session(config, up) as c:
        up.queue += [tool(**args), {'role':'assistant','content':'Job succeeded! Download from an invented link.'}]
        accepted = (await chat(c, 'ESMFold2', cid)).json()
        assert accepted['outcome'] == 'job_submitted' and len(accepted['job_ids']) == 1
        assert 'succeeded' not in accepted['assistant_message'] and '4 aa' in accepted['assistant_message']
        up.queue += [tool(sequence='ACDE', model='protenix'), plan('result')]
        switched = (await chat(c, 'Use the same sequence with Protenix.', cid)).json()
        assert 'Protenix' in switched['assistant_message'] and switched['outcome'] == 'job_submitted'
        hist = (await c.get('/api/conversations/'+cid)).json()
        assert [m['role'] for m in hist['messages']] == ['user','assistant'] * 3 and hist['job_ids'] == accepted['job_ids']+switched['job_ids']
        up.queue += [tool(sequence='ACDE',model='protenix'), plan('result')]
        unrelated = (await chat(c,'同一序列改用 Protenix')).json()
        assert unrelated['conversation_id'] != cid and unrelated['outcome'] == 'ask_sequence'


async def test_user_supplies_model_first_and_no_default_is_chosen(client, up):
    up.queue += [plan('ask_sequence', model='protenix'), tool(sequence='ACDE',model='protenix'), plan('result')]
    first = (await chat(client,'请用 Protenix')).json()
    assert first['outcome'] == 'ask_sequence'
    second = (await chat(client,'>short\naC\nd E', first['conversation_id'])).json()
    assert second['outcome'] == 'job_submitted' and '4 aa' in second['assistant_message']


async def test_status_reads_current_conversation_not_a_guessed_id(config, client, up):
    jid = str(uuid4())
    up.queue += [plan()]
    origin = (await chat(client,'Hello')).json()['conversation_id']
    with closing(sqlite3.connect(config.db)) as db, db:
        db.execute('INSERT INTO jobs(id,conversation_id,sequence,model,model_version,mode,status,created_at,parameters) VALUES(?,?,?,?,?,?,?,?,?)',
                   (jid,origin,'ACDE','protenix','test-only','mock','running','2026-11-19T00:00:00Z','{}'))
    for conv, text, expected in [(origin,'Has it finished?', 'job_status'),(origin,'Check '+str(uuid4()),'ask_job'),
                                (None,'Check '+jid,'job_not_found'),(None,'Has it finished?','ask_job')]:
        up.queue += [tool('get_job_status', job_id=jid),plan('result')]
        reply = (await chat(client,text,conv)).json()
        assert reply['outcome'] == expected
        if expected == 'job_status':
            assert 'running' in reply['assistant_message'] and reply['job_ids'] == [jid]
        else:
            assert reply['job_ids'] == []


async def test_deduplicates_tool_dispatch_and_http_retries(client, up):
    up.queue += [tool(sequence='ACDE',model='protenix'), tool(cid='call_2',sequence='ACDE',model='protenix'), plan('result')]
    rid, msg = str(uuid4()), 'Use Protenix. Sequence: ACDE'
    a, b = (await chat(client,msg,rid=rid)).json(), (await chat(client,msg,rid=rid)).json()
    assert a == b and len(a['job_ids']) == 1 and len(up.sent) == 3
    assert up.sent[-1]['tool_choice'] == 'none'
    assert (await chat(client,'different',rid=rid)).status_code == 409
    recovered = (await client.get('/api/conversations/'+a['conversation_id'])).json()
    assert len(recovered['messages']) == 2 and recovered['job_ids'] == a['job_ids']


@pytest.mark.parametrize(('code','name'), [(401,'llm_auth'),(402,'llm_balance'),(429,'llm_rate_limit'),(500,'llm_upstream'),(302,'llm_upstream')])
async def test_provider_errors_no_leaks_or_fake_turn(config, client, up, code, name):
    up.queue += [httpx.Response(code, headers={'Location':'https://example.invalid/'},json={'error':'sensitive-upstream-detail'})]
    response = await chat(client,'Hello')
    assert response.status_code >= 500 and response.json()['error']['code'] == name
    assert 'sensitive-upstream-detail' not in response.text and 'offline-placeholder' not in response.text
    with closing(sqlite3.connect(config.db)) as db:
        assert db.execute('SELECT count(*) FROM turns').fetchone()[0] == 0


@pytest.mark.parametrize('overrides', [{'key':''},{'base_url':'https://example.invalid'},{'model':''}])
async def test_missing_config_and_untrusted_host_do_not_send(config, up, overrides):
    async with session(replace(config,**overrides),up) as c:
        assert not (await c.get('/api/health')).json()['llm_configured']
        assert (await chat(c,'Hello')).json()['error']['code'] == 'llm_config'
        assert not up.sent


async def test_tool_loop_exhaustion_never_reports_success(client, up):
    up.queue += [tool('unknown_tool'),tool('unknown_tool'),tool('unknown_tool')]
    r = await chat(client,'Hi')
    assert r.status_code == 502 and r.json()['error']['code'] == 'tool_limit'
    assert len(up.sent) == 3


async def test_wrong_final_format_requires_real_correction(client, up):
    up.queue += [plan('result'),plan('help')]
    assert (await chat(client,'Hello')).json()['outcome'] == 'help' and len(up.sent) == 2
    up.queue += [plan('result'),plan('result')]
    assert (await chat(client,'Hello')).json()['error']['code'] == 'llm_protocol'


async def test_bare_model_answer_requires_a_real_provider_call(client, up):
    up.queue += [plan('ask_model', sequence='ACDE')]
    cid = (await chat(client,'Sequence: ACDE')).json()['conversation_id']
    up.queue += [plan('help'),tool(sequence='ACDE',model='esmfold2'),plan('result')]
    reply = (await chat(client,'ESMFold2',cid)).json()
    assert up.sent[1]['tool_choice'] == {'type':'function','function':{'name':'predict_structure'}}
    assert reply['outcome'] == 'job_submitted' and '4 aa' in reply['assistant_message']


async def test_user_supplies_model_first_despite_model_guessing_sequence(client, up):
    up.queue += [tool(sequence='ACDE',model='protenix'),plan('result'),tool(sequence='MFY',model='protenix'),plan('result')]
    first = (await chat(client,'使用 Protenix')).json()
    assert first['outcome'] == 'ask_sequence'
    assert (await chat(client,'MFY',first['conversation_id'])).json()['outcome'] == 'job_submitted'


async def test_bad_raw_sequence_explained_even_if_model_responds_with_help(client, up):
    up.queue += [plan('help')]
    assert (await chat(client,'ABCZ123')).json()['outcome'] == 'invalid_residues'


async def test_conflicting_call_ids_never_dispatch_twice(client, up):
    up.queue += [tool(sequence='ACDE',model='protenix'),tool(sequence='AAAA',model='protenix'),plan('result')]
    reply = (await chat(client,'Use Protenix. Sequence: ACDE')).json()
    assert reply['outcome'] == 'call_conflict' and len(reply['job_ids']) == 1  # only the first, valid call


async def test_llm_failure_after_tool_call_creates_no_orphan(config, client, up):
    up.queue += [tool(sequence='ACDE',model='protenix'), httpx.Response(429)]
    reply = await chat(client,'Use Protenix. Sequence: ACDE')
    assert reply.status_code == 503
    with closing(sqlite3.connect(config.db)) as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM turns').fetchone()[0] == 0


async def test_real_mode_does_not_substitute_mock(config, up):
    up.queue += [tool(sequence='ACDE',model='protenix'), plan('result')]
    async with session(replace(config, protenix_mode='real'), up) as c:
        r = (await chat(c,'Use Protenix. Sequence: ACDE')).json()
        assert r['outcome']=='real_unavailable' and r['job_ids']==[]
        assert (await c.get('/api/health')).json()['prediction_modes']=={'esmfold2':'mock','protenix':'real'}
