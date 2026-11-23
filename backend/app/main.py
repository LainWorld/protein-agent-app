from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.agent import Agent
from app.config import PublicError, Settings, settings
from app.llm_client import DeepSeek
from app.jobs import JobService
from app.schemas import ChatRequest, ChatResponse, Context, Conversation, HealthResponse, JobView
from app.storage import Store


def create_app(config: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        conf = config or settings()
        store = Store(conf.db)
        store.initialize()
        async with httpx.AsyncClient(transport=transport, trust_env=False) as http:
            jobs = JobService(store, conf, http)
            jobs.start()
            app.state.store, app.state.config, app.state.jobs = store, conf, jobs
            app.state.agent = Agent(DeepSeek(conf, http), store)
            try:
                yield
            finally:
                await jobs.stop()

    app = FastAPI(title='Protein Chat', version='0.5.0', lifespan=lifespan,
                  description='Single-chain folding with OpenProtein or Biohub ESMFold2, the Protenix Mini CLI and explicit Mock modes.')
    busy_requests: set[UUID] = set()
    busy_chats: set[UUID] = set()

    @app.exception_handler(PublicError)
    async def service_error(_request: Request, exc: PublicError):
        return JSONResponse({'error': {'code': exc.code, 'message': exc.message}}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _error: RequestValidationError):
        return JSONResponse({'error': {'code': 'invalid_request', 'message': '请输入 1–4000 字符的非空消息，并使用有效 UUID。'}}, status_code=422)

    @app.get('/api/health', response_model=HealthResponse)
    async def health():
        conf = app.state.config
        modes = {m: conf.mode(m) for m in ('esmfold2','protenix')}
        configured = {model: (model, mode) in app.state.jobs.adapters for model, mode in modes.items()}
        return HealthResponse(llm_configured=conf.configured, prediction_enabled=any(configured.values()),
                              prediction_modes=modes, prediction_configured=configured)

    @app.get('/api/jobs/{jid}', response_model=JobView)
    async def job(jid: UUID, conversation_id: UUID):
        return app.state.jobs.view(conversation_id, jid)

    @app.get('/api/jobs/{jid}/structure')
    async def structure(jid: UUID, conversation_id: UUID, download: bool = False):
        blob, name = app.state.jobs.structure(conversation_id, jid)
        disposition = 'attachment' if download else 'inline'
        return Response(blob, media_type='chemical/x-pdb', headers={'Cache-Control':'no-store',
                        'Content-Disposition': f'{disposition}; filename="{name}"'})

    @app.get('/api/conversations/{cid}', response_model=Conversation)
    async def recover(cid: UUID):
        return app.state.store.recover(cid)

    @app.post('/api/chat', response_model=ChatResponse)
    async def chat(payload: ChatRequest):
        store, rid = app.state.store, payload.request_id or uuid4()
        if reply := store.replay(rid, payload):
            return reply
        cid = payload.conversation_id or uuid4()
        if rid in busy_requests or cid in busy_chats:
            raise PublicError(409, 'turn_busy', '此会话仍在处理上一条消息，请稍后重试。')
        ctx = store.context(cid) if payload.conversation_id else Context()
        busy_requests.add(rid)
        busy_chats.add(cid)
        try:
            submission = app.state.jobs.transaction(cid)
            reply, trace = await app.state.agent.run(payload.message, cid, ctx, submission)
            store.commit_turn(rid, payload, ctx, reply, trace, submission.rows.values())
            if submission.rows:
                app.state.jobs.wake.set()
            return reply
        finally:
            busy_requests.discard(rid)
            busy_chats.discard(cid)

    return app


app = create_app()
