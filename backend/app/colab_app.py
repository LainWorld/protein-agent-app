"""Mac chat with an interactive free-Colab Protenix execution option."""
from contextlib import asynccontextmanager
from dataclasses import replace
import json
from uuid import UUID

from fastapi import Request, Response

from app.adapters.colab_handoff import MAX_RESULT_BYTES, ColabHandoff, notebook
from app.config import PublicError, settings
from app.main import create_app


def create_colab_app(config=None, transport=None):
    app = create_app(replace(config or settings(), protenix_mode='real'), transport)
    original = app.router.lifespan_context
    handoff = ColabHandoff()

    @asynccontextmanager
    async def lifespan(application):
        async with original(application):
            application.state.jobs.adapters['protenix', 'real'] = handoff
            yield
    app.router.lifespan_context = lifespan

    def pending(cid, jid):
        row = app.state.store.job(cid, jid)
        if row is None:
            raise PublicError(404, 'job_not_found', '本会话没有这个任务。')
        future = handoff.waiting.get(str(jid))
        if row['status'] != 'running' or future is None or future.done():
            raise PublicError(409, 'not_waiting', '该任务尚未开始、已结束或已收到结果。')
        return row, future

    @app.get('/api/jobs/{jid}/colab-notebook')
    async def download_notebook(conversation_id: UUID, jid: UUID):
        row, _ = pending(conversation_id, jid)
        return Response(notebook(str(jid), row['sequence']), media_type='application/x-ipynb+json',
                        headers={'Content-Disposition': f'attachment; filename="protenix-{jid}.ipynb"',
                                 'Cache-Control': 'no-store'})

    @app.post('/api/jobs/{jid}/colab-result')
    async def upload(conversation_id: UUID, jid: UUID, request: Request):
        pending(conversation_id, jid)
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise PublicError(415, 'format', '请选择 Colab 最后一个单元下载的 JSON。')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_RESULT_BYTES:
                raise PublicError(413, 'size', '文件超过 10 MB。')
            data.extend(chunk)
        row, future = pending(conversation_id, jid)
        try:
            receipt = json.loads(data)
            handoff.validate(receipt, str(jid), row['sequence'])
        except (KeyError, TypeError, ValueError, IndexError, AttributeError, RecursionError):
            raise PublicError(422, 'receipt', '文件与任务不符或运行记录不完整，请选择本任务下载的 JSON。') from None
        future.set_result(receipt)
        return {'received': True}
    return app
