"""Isolated *test upstream* for browser QA. Cannot use DeepSeek or a real predictor.

Run only on loopback as documented. Every launch uses a new temporary database.
"""

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile

import httpx

from app.config import Settings
from app.adapters.mock import MockAdapter
from app.main import create_app

UBQ = 'MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'
_temp = tempfile.TemporaryDirectory(prefix='protein-chat-browser-test-')


def scripted_response(req):
    last = json.loads(req.content)['messages'][-1]
    if last['role']=='tool':
        msg={'role':'assistant','content':'{"act":"result","lang":"zh"}'}
    elif last['role']=='user' and last['content'] in {f'Use {m}. Sequence: {UBQ}' for m in ('ESMFold2','Protenix')}:
        model=last['content'].split()[1][:-1].lower()
        msg={'role':'assistant','tool_calls':[{'id':'demo-call','type':'function','function':{
            'name':'predict_structure','arguments':json.dumps({'model':model,'sequence':UBQ})}}]}
    else:
        msg={'role':'assistant','content':'{"act":"help","lang":"zh"}'}
    return httpx.Response(200,json={'choices':[{'message':msg,'finish_reason':'tool_calls' if 'tool_calls' in msg else 'stop'}]})


class Broken(MockAdapter):
    async def predict(self, seq, directory, params):
        await asyncio.sleep(params['mock_delay_seconds'])
        if self.model=='esmfold2':
            raise RuntimeError('deliberate test execution error')
        target=directory/'structure.pdb'
        target.write_text(f'REMARK 950 JOB {directory.name}\nEND\n')
        return target


app = create_app(Settings('deepseek','https://api.deepseek.com','offline','offline',
                 Path(_temp.name)/'demo.sqlite3', mock_delay=3), httpx.MockTransport(scripted_response))
original_lifespan=app.router.lifespan_context


@asynccontextmanager
async def fault_lifespan(app):
    async with original_lifespan(app):
        app.state.jobs.adapters={(model, 'mock'):Broken(model) for model in ('esmfold2','protenix')}
        yield


app.router.lifespan_context=fault_lifespan
