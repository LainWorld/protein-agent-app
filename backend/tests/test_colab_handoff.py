"""Local transfer acceptance. Coordinates from a fixture, GPU/CLI/LLM doubled."""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

import gemmi
import httpx
import pytest

from app.colab_app import create_colab_app
from app.config import Settings
from test_jobs import install_cli_double, route, terminal

SEQ = 'DQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'


@pytest.mark.anyio
async def test_mac_chat_handoff_38(tmp_path, monkeypatch, anyio_backend):
    if anyio_backend != 'asyncio':
        pytest.skip('asyncio worker')
    from app.adapters.mock import FIXTURE
    cli = Path(install_cli_double(tmp_path, 'success')['protenix_executable'])
    (cli.parent/'sequence').write_text(SEQ)
    reference = gemmi.read_structure(str(FIXTURE))
    reference.remove_waters()
    chain = reference[0][0]
    while len(chain) > len(SEQ):
        del chain[0]
    block = reference.make_mmcif_document().sole_block()
    block.name = 'RUNID_sample_0_predicted_by_protenix'
    block.set_pair('_entry.id', 'RUNID')
    (cli.parent/'reference.cif').write_text(block.as_string())
    calls = [{'role':'assistant','tool_calls':[{'id':'local-call','type':'function','function':{
        'name':'predict_structure','arguments':json.dumps({'model':'protenix','sequence':SEQ})}}]},
        {'role':'assistant','content':'{"act":"result","lang":"en"}'}]
    def reply(request):
        msg = calls.pop(0)
        return httpx.Response(200,json={'choices':[{'message':msg,'finish_reason':'tool_calls' if 'tool_calls' in msg else 'stop'}]})
    upstream = httpx.MockTransport(reply)
    app = create_colab_app(Settings('deepseek','https://api.deepseek.com','test','test',tmp_path/'store'/'app.sqlite3'),upstream)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://local') as c:
        result = (await c.post('/api/chat',json={'message':f'Use Protenix. Sequence: {SEQ}'})).json()
        cid, jid = result['conversation_id'], result['job_ids'][0]
        base = f'/api/jobs/{jid}/colab-'
        query = f'?conversation_id={cid}'
        async with asyncio.timeout(3):
            while (await c.get(route(cid,jid))).json()['status'] != 'running':
                await asyncio.sleep(.01)
        nb = (await c.get(base+'notebook'+query)).json()
        code = [x for x in nb['cells'] if x['cell_type']=='code']
        assert len(code)==4 and SEQ in ''.join(code[-1]['source']) and jid in ''.join(code[-1]['source'])
        for cell in code:
            compile(''.join(cell['source']),cell['id'],'exec')
        assert (await c.get(base+'notebook?conversation_id='+str(uuid4()))).status_code == 404
        assert (await c.get(route(cid,jid,True))).status_code == 409
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'colab'))
        import chat_result
        monkeypatch.setattr(sys, 'executable', str(cli.with_name('python')))
        await chat_result.run(tmp_path, jid, SEQ)
        receipt = json.loads((tmp_path/'mac-chat'/jid/f'protenix-result-{jid}.json').read_bytes())
        assert receipt['status']=='succeeded'
        assert (await c.post(base+'result'+query,json={**receipt,'job_id':str(uuid4())})).status_code == 422
        assert (await c.post(base+'result'+query,json=receipt)).status_code == 200
        job = await terminal(c,cid,jid)
        assert job['result_available'] and job['length']==38 and job['parameters']['execution']=='colab_notebook'
        assert (await c.post(base+'result'+query,json=receipt)).status_code == 409
        inline = (await c.get(route(cid,jid,True))).content
        assert inline == (await c.get(route(cid,jid,True)+'&download=true')).content
        assert jid.encode() in inline and b'MODE REAL' in inline
