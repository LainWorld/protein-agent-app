"""The only boundary that can send application data to DeepSeek."""

import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import PublicError, Settings


class Function(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    arguments: str = Field(max_length=16000)


class ToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    type: Literal['function']
    function: Function


class Assistant(BaseModel):
    role: Literal['assistant']
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    def wire(self) -> dict:
        return self.model_dump(exclude={'tool_calls'} if not self.tool_calls else set())


def protocol_error(reason: str = 'response_shape') -> PublicError:
    # Reasons are fixed local labels. Never log provider text, validation inputs or headers.
    logging.getLogger(__name__).warning('DeepSeek protocol: %s', reason)
    return PublicError(502, 'llm_protocol', 'DeepSeek 返回了不完整或无法解析的回复，请重试。')


class DeepSeek:
    def __init__(self, config: Settings, http: httpx.AsyncClient):
        self.config, self.http = config, http

    async def request(self, path: str, payload: dict | None = None) -> dict:
        self.config.require_llm(selecting_model=path == '/models')
        try:
            response = await self.http.request('GET' if payload is None else 'POST', self.config.base_url + path,
                                               json=payload, headers={'Authorization': f'Bearer {self.config.key}'},
                                               timeout=httpx.Timeout(25.0, connect=6.0), follow_redirects=False)
        except httpx.TimeoutException:
            raise PublicError(504, 'llm_timeout', '连接 DeepSeek 超时，请稍后重试。') from None
        except httpx.RequestError:
            raise PublicError(503, 'llm_connection', '后端无法连接 DeepSeek，请检查网络。') from None
        errors = {401: ('llm_auth', 'DeepSeek 拒绝了密钥，请检查服务端配置。'),
                  403: ('llm_access', 'DeepSeek 拒绝访问，请检查账户权限。'),
                  402: ('llm_balance', 'DeepSeek 账户余额不足，请检查额度。'),
                  429: ('llm_rate_limit', 'DeepSeek 限流，请稍后重试。')}
        if response.status_code != 200:
            code, message = errors.get(response.status_code, ('llm_upstream', f'DeepSeek 请求失败（HTTP {response.status_code}）。'))
            raise PublicError(503 if response.status_code in errors else 502, code, message)
        try:
            data = response.json()
        except ValueError:
            raise protocol_error() from None
        if not isinstance(data, dict):
            raise protocol_error()
        return data

    async def complete(self, messages: list[dict], tools: list[dict], choice: str | dict = 'auto') -> Assistant:
        data = await self.request('/chat/completions', {'model': self.config.model, 'messages': messages,
                                  'tools': tools, 'tool_choice': choice, 'thinking': {'type': 'disabled'},
                                  'max_tokens': 1536, 'stream': False})
        try:
            first = data['choices'][0]
            reply = Assistant.model_validate(first['message'])
            reason = first['finish_reason']
            if not ((reason == 'tool_calls' and reply.tool_calls) or
                    (reason == 'stop' and not reply.tool_calls and (reply.content or '').strip())):
                raise protocol_error('incomplete_completion')
            return reply
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise protocol_error() from None
