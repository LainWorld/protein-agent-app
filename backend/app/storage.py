"""One local SQLite database. A completed chat turn and its context commit together."""

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from app.config import PublicError
from app.schemas import ChatRequest, ChatResponse, Context, Conversation, Message


class Store:
    def __init__(self, path: Path):
        self.path = path

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def initialize(self) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, context TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id), new_conversation INTEGER NOT NULL,
                    user_text TEXT NOT NULL, reply_json TEXT NOT NULL, tools_json TEXT NOT NULL, utc TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS turns_by_conversation ON turns(conversation_id,id);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    sequence TEXT NOT NULL, model TEXT NOT NULL, model_version TEXT NOT NULL, mode TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
                    parameters TEXT NOT NULL, seed INTEGER, output_path TEXT, error TEXT);
                CREATE INDEX IF NOT EXISTS jobs_by_conversation ON jobs(conversation_id,created_at);
            ''')
            if 'sha256' not in {r[1] for r in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN sha256 TEXT')
            db.commit()

    def context(self, cid: UUID) -> Context:
        with closing(self.connect()) as db:
            row = db.execute('SELECT context FROM conversations WHERE id=?', (str(cid),)).fetchone()
        if row is None:
            raise PublicError(404, 'conversation_not_found', '这个会话不存在，请开始新对话。')
        return Context.model_validate_json(row[0])

    def messages(self, cid: UUID, *, recent: bool = False) -> list[Message]:
        with closing(self.connect()) as db:
            sql = 'SELECT user_text,reply_json FROM turns WHERE conversation_id=? ORDER BY id '
            rows = db.execute(sql + ('DESC LIMIT 6' if recent else 'ASC'), (str(cid),)).fetchall()
        return [msg for row in (reversed(rows) if recent else rows) for msg in (
            Message(role='user', text=row[0]),
            Message(role='assistant', text=ChatResponse.model_validate_json(row[1]).assistant_message))]

    def job(self, cid: UUID, job_id: UUID):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND conversation_id=?',
                             (str(job_id), str(cid))).fetchone()
        return dict(row) if row else None

    def job_ids(self, cid: UUID) -> list[UUID]:
        with closing(self.connect()) as db:
            return [UUID(row[0]) for row in db.execute(
                'SELECT id FROM jobs WHERE conversation_id=? ORDER BY created_at, id', (str(cid),))]

    def recover(self, cid: UUID) -> Conversation:
        self.context(cid)  # unknown IDs must never silently create a new conversation
        return Conversation(conversation_id=cid, messages=self.messages(cid), job_ids=self.job_ids(cid))

    def replay(self, rid: UUID, req: ChatRequest) -> ChatResponse | None:
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM turns WHERE request_id=?', (str(rid),)).fetchone()
        if not row:
            return None
        origin = None if row['new_conversation'] else UUID(row['conversation_id'])
        if origin != req.conversation_id or req.message != row['user_text']:
            raise PublicError(409, 'request_conflict', '请求编号已被其他消息使用，请重新发送。')
        return ChatResponse.model_validate_json(row['reply_json'])

    def commit_turn(self, rid: UUID, req: ChatRequest, ctx: Context, reply: ChatResponse, trace: list[dict], jobs=()):
        cid = str(reply.conversation_id)
        with closing(self.connect()) as db, db:
            db.execute('INSERT INTO conversations(id,context) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET context=excluded.context',
                       (cid, ctx.model_dump_json()))
            # A failed LLM follow-up / failed transaction leaves no orphaned job.
            db.executemany('INSERT INTO jobs(id,conversation_id,sequence,model,model_version,mode,status,created_at,parameters,seed) '
                           "VALUES(:id,:conversation_id,:sequence,:model,:model_version,:mode,'queued',:created_at,:parameters,:seed)", jobs)
            db.execute('INSERT INTO turns(request_id,conversation_id,new_conversation,user_text,reply_json,tools_json,utc) '
                       'VALUES (?,?,?,?,?,?,?)', (str(rid), cid, req.conversation_id is None, req.message,
                       reply.model_dump_json(), json.dumps(trace), datetime.now(timezone.utc).isoformat()))
