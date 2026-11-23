"""Server-only config. Nothing here is exposed to Vite or returned by health."""

import os
import math
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from app.adapters.protenix import MODEL as PROTENIX_MINI

BACKEND = Path(__file__).resolve().parents[1]
ENV_FILE = BACKEND / '.env'
FLASH = 'deepseek-flash'
BIOHUB_URL = 'https://biohub.ai'
ESMFOLD2_FAST = 'esmfold2-fast-2026-05'


class PublicError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Settings:
    provider: str
    base_url: str
    model: str
    key: str = field(repr=False)
    db: Path
    esmfold2_mode: str = 'mock'
    protenix_mode: str = 'mock'
    mock_delay: float = 3.0
    job_timeout: float = 30.0
    esmfold2_key: str = field(default='', repr=False)
    esmfold2_url: str = BIOHUB_URL
    esmfold2_model: str = ESMFOLD2_FAST
    protenix_executable: str = ''
    protenix_model: str = PROTENIX_MINI
    protenix_root: Path = field(default_factory=Path.home)

    esmfold2_provider: str = 'biohub'
    openprotein_username: str = field(default='', repr=False)
    openprotein_password: str = field(default='', repr=False)

    @property
    def protenix_cli(self) -> Path | None:
        if self.protenix_model == PROTENIX_MINI and self.protenix_executable:
            path = Path(self.protenix_executable).expanduser()
            if path.is_absolute() and path.is_file() and os.access(path, os.X_OK):
                return path
        return None

    @property
    def biohub_configured(self) -> bool:
        return bool(self.esmfold2_key and self.esmfold2_url == BIOHUB_URL and self.esmfold2_model == ESMFOLD2_FAST)

    def mode(self, model: str) -> str:
        return {'esmfold2': self.esmfold2_mode, 'protenix': self.protenix_mode}[model]

    def require_llm(self, *, selecting_model: bool = False) -> None:
        if (self.provider != 'deepseek' or not self.key or (not self.model and not selecting_model)
                or self.base_url not in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'}):
            raise PublicError(503, 'llm_config', '请在服务端配置 DeepSeek 密钥、官方地址和模型名，然后重启后端。')

    @property
    def configured(self) -> bool:
        try:
            self.require_llm()
            return True
        except PublicError:
            return False


def settings() -> Settings:
    values = dotenv_values(ENV_FILE, interpolate=False)

    def value(key: str) -> str:
        return os.environ.get(key, values.get(key) or '').strip()

    def seconds(key: str, default: float, minimum: float) -> float:
        try:
            n = float(value(key) or default)
        except ValueError:
            n = math.nan
        if not math.isfinite(n) or not minimum <= n <= 3600:
            raise ValueError(f'{key} must be between {minimum} and 3600 seconds.')
        return n

    def mode(key: str) -> str:
        selected = os.environ.get(key, values.get(key, 'mock'))
        if selected not in {'mock', 'real'}:
            raise ValueError(f'{key} must be mock or real.')
        return selected

    provider = value('ESMFOLD2_PROVIDER').lower() or 'biohub'
    if provider not in {'biohub', 'openprotein'}:
        raise ValueError('ESMFOLD2_PROVIDER must be biohub or openprotein.')
    return Settings(value('LLM_PROVIDER').lower(), value('LLM_BASE_URL').rstrip('/'),
                    value('LLM_MODEL'), value('LLM_API_KEY'), BACKEND.parent / 'data' / 'app.sqlite3',
                    mode('ESMFOLD2_MODE'), mode('PROTENIX_MODE'), seconds('MOCK_DELAY_SECONDS', 3, 0),
                    seconds('JOB_TIMEOUT_SECONDS', 30, 0.01), esmfold2_key=value('ESMFOLD2_API_KEY'),
                    esmfold2_url=(value('ESMFOLD2_API_URL') or BIOHUB_URL).rstrip('/'),
                    esmfold2_model=value('ESMFOLD2_MODEL') or ESMFOLD2_FAST,
                    esmfold2_provider=provider, openprotein_username=value('OPENPROTEIN_USERNAME'),
                    openprotein_password=os.environ.get('OPENPROTEIN_PASSWORD', values.get('OPENPROTEIN_PASSWORD') or ''),
                    protenix_executable=value('PROTENIX_EXECUTABLE') or shutil.which('protenix') or '',
                    protenix_model=value('PROTENIX_MODEL') or PROTENIX_MINI,
                    protenix_root=Path(value('PROTENIX_ROOT_DIR') or Path.home()).expanduser().resolve())
