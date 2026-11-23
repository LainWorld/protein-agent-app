"""Public chat contracts and server-owned conversation context."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    message: str = Field(strict=True, min_length=1, max_length=4000)
    conversation_id: UUID | None = None
    request_id: UUID | None = None  # reuse on a manual retry; never a conversation selector

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value


class ChatResponse(BaseModel):
    conversation_id: UUID
    assistant_message: str
    job_ids: list[UUID] = Field(default_factory=list)
    chat_mode: Literal['llm'] = 'llm'
    outcome: str


class Message(BaseModel):
    role: Literal['user', 'assistant']
    text: str


class Conversation(BaseModel):
    conversation_id: UUID
    messages: list[Message]
    job_ids: list[UUID]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    chat_mode: Literal['llm'] = 'llm'
    llm_configured: bool  # health does not make a billable call
    prediction_enabled: bool
    prediction_modes: dict[str, Literal['mock', 'real']]
    prediction_configured: dict[str, bool]  # local adapter settings, not upstream authorization or balance


FoldModel = Literal['esmfold2', 'protenix']


class JobView(BaseModel):
    id: UUID
    conversation_id: UUID
    model: FoldModel
    model_version: str
    mode: Literal['mock', 'real']
    status: Literal['queued', 'running', 'succeeded', 'failed']
    length: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    parameters: dict
    seed: int | None
    error: str | None
    error_message: str | None
    fixture_source: str | None
    result_available: bool
    download_name: str | None
    sha256: str | None


class Context(BaseModel):
    pending_sequence: str | None = None
    pending_model: FoldModel | None = None
    last_sequence: str | None = None
    lang: Literal['en', 'zh'] = 'zh'
