"""Check the running local stack. Only --live sends billable chat requests."""

import argparse
import hashlib
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

DIRECT = 'http://127.0.0.1:8000'
PROXY = 'http://127.0.0.1:5173'
# RCSB PDB 1UBQ, chain A. Mock copies an existing structure even for this input.
UBQ = 'MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'


def api(base, path, payload=None, expected=200):
    req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={'Content-Type': 'application/json'})
    try:
        with urlopen(req, timeout=70 if payload else 8) as resp:
            status, body = resp.status, json.load(resp)
    except HTTPError as exc:
        status = exc.code
        try:
            body = json.load(exc)
        except ValueError:
            body = {}
    if status != expected:
        raise ValueError(f'{path}: HTTP {status}, expected {expected}; {body.get("error", {}).get("code", "unknown")}')
    return body


def live():
    if api(DIRECT,'/api/health')['prediction_modes'] != {'esmfold2':'mock','protenix':'mock'}:
        raise ValueError('This smoke requires both routes to be explicitly set to Mock.')
    cid = None
    def turn(message, outcome):
        nonlocal cid
        reply = api(PROXY, '/api/chat', {'message': message, 'request_id': str(uuid4()), 'conversation_id': cid})
        assert cid is None or reply['conversation_id'] == cid
        cid = str(UUID(reply['conversation_id']))
        if reply['outcome'] != outcome:
            raise ValueError(f'expected {outcome}, received {reply["outcome"]}')
        return reply
    first = turn(f'请预测这条序列：\n{UBQ}', 'ask_model')
    assert not first['job_ids'] and '76' in first['assistant_message']
    print('PASS live: 76 aa saved; model requested, no job.', flush=True)
    jobs=[]
    for message, model in [('ESMFold2','esmfold2'), ('Use the same sequence with Protenix.','protenix')]:
        reply=turn(message,'job_submitted')
        assert len(reply['job_ids'])==1 and 'Mock' in reply['assistant_message']
        jid=str(UUID(reply['job_ids'][0])); jobs.append(jid)
        path='/api/jobs/'+jid; query='?conversation_id='+cid
        deadline=time.monotonic()+45
        states=[]
        while time.monotonic()<deadline:
            j=api(PROXY,path+query)
            states.append(j['status'])
            if j['status'] in {'failed','succeeded'}: break
            assert not j['result_available']
            time.sleep(2)
        assert j['status']=='succeeded' and j['model']==model and j['length']==76 and j['mode']=='mock'
        assert j['result_available'] and j['fixture_source']=='https://www.rcsb.org/structure/1UBQ'
        with urlopen(PROXY+path+'/structure'+query,timeout=8) as shown, urlopen(PROXY+path+'/structure'+query+'&download=true',timeout=8) as dl:
            bs=dl.read()
            assert bs==shown.read() and hashlib.sha256(bs).hexdigest()==j['sha256']
            assert j['download_name']==f'{model}-mock-{jid}.pdb' and j['download_name'] in dl.headers['Content-Disposition']
            assert b'NOT A PREDICTION' in bs and jid.encode() in bs
        print(f'PASS live: {model} mock {jid} · {states} · verified file SHA-256 {j["sha256"]}',flush=True)
    assert jobs[0]!=jobs[1]
    status=turn(f'请查询本会话任务 {jobs[1]} 的真实状态。','job_status')
    assert status['job_ids']==[jobs[1]] and 'succeeded' in status['assistant_message']
    history = api(DIRECT, '/api/conversations/' + cid)
    assert len(history['messages'])==8 and history['job_ids']==jobs
    print(f'PASS: truthful status, four turns and two mock jobs recovered. Conversation {cid}.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='send 4 live turns using the public ubiquitin example')
    args = parser.parse_args()
    try:
        for base in (DIRECT, PROXY):
            h = api(base, '/api/health')
            assert h['status'] == 'ok' and h['chat_mode'] == 'llm' and 'prediction_modes' in h
            assert api(base, '/api/chat', {'message': '  '}, 422)['error']['code'] == 'invalid_request'
            assert api(base, '/api/conversations/' + str(uuid4()), expected=404)['error']['code'] == 'conversation_not_found'
            print(f'PASS {base}: health, POST validation, unknown conversation (no LLM calls).', flush=True)
        if args.live:
            live()
    except (OSError, URLError, AssertionError, ValueError, KeyError) as exc:
        sys.exit(f'FAIL: {exc!s}')
