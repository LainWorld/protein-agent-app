"""Visit the built app using a temporary loopback backend, scripted LLM and executable CLI double."""

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import tempfile

import httpx
import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
from app.config import Settings
from app.main import create_app
from test_jobs import UBQ, install_cli_double


def upstream(request):
    last = json.loads(request.content)['messages'][-1]
    if last['role'] == 'user' and last['content'] == '请用 Protenix 预测这条序列：\n' + UBQ:
        args = json.dumps(dict(sequence=UBQ, model='protenix'))
        reply = dict(role='assistant', tool_calls=[dict(id='offline-call', type='function',
                     function=dict(name='predict_structure', arguments=args))])
    elif last['role'] == 'tool':
        reply = dict(role='assistant', content='{"act":"result","lang":"zh"}')
    else:
        raise ValueError('Unexpected browser test message')
    return httpx.Response(200, json={'choices': [{'message': reply, 'finish_reason': 'tool_calls' if 'tool_calls' in reply else 'stop'}]})


async def main():
    with tempfile.TemporaryDirectory(prefix='round5-offline-') as folder, socket.socket() as listener:
        tmp = Path(folder)
        config = Settings('deepseek', 'https://api.deepseek.com', 'offline', 'test-only', tmp/'test.sqlite3',
                          **install_cli_double(tmp, 'success'))
        app = create_app(config, httpx.MockTransport(upstream))
        app.mount('/', StaticFiles(directory=ROOT/'frontend/dist', html=True))
        listener.bind(('127.0.0.1', 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if serving.done():
                        await serving
                        raise RuntimeError('Temporary backend stopped')
                    await asyncio.sleep(.05)
            print('OFFLINE · scripted LLM and CLI · temporary database, coordinates and screenshots', flush=True)
            check = await asyncio.create_subprocess_exec('bash', str(ROOT/'scripts/check-browser.sh'), '--offline-protenix',
                                                        str(listener.getsockname()[1]), folder)
            return await check.wait()
        finally:
            server.should_exit = True
            await serving


async def round6_offline():
    from test_round6 import ev, run, setup_run

    with tempfile.TemporaryDirectory(prefix='round6-offline-') as folder:
        work = Path(folder)
        app, provider_calls = setup_run(work)
        print('OFFLINE · 临时数据库、DeepSeek 和 CLI 替身、1UBQ 测试坐标', flush=True)
        async with run.loopback(app) as base, httpx.AsyncClient(base_url=base, trust_env=False) as client:
            job = await run.capture(app, client, work)
            await run.check_live_view(base, work, job, location='offline_backend', env=dict(os.environ))
            path = ev.pack(work)
            first = ev.check_browser(ev.load(path), job, 'offline_backend')
            assert first['refresh'] and first['download_sha256'] == job['sha256']
        await run.mac(path, interactive=False)
        second = ev.read_json(path.with_name(path.stem+'-mac')/'browser.json')
        assert second['refresh'] and second['download_sha256'] == first['download_sha256']
        assert provider_calls == ['user','tool']
        print('PASS OFFLINE · 原任务与归档的两次画布检查、下载和刷新，只有一条聊天', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--round6']:
        asyncio.run(round6_offline())
    elif not sys.argv[1:]:
        raise SystemExit(asyncio.run(main()))
    else:
        raise SystemExit('Use --round6 for the chat evidence and read-only archive check')
