"""Authenticate and read the model catalog entry without submitting a fold."""

import asyncio
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.adapters.openprotein import OpenProteinAdapter, OpenProteinError
from app.config import settings
from app.jobs import ERRORS
from app.structures import InvalidOutput


async def main() -> None:
    config = settings()
    if not config.openprotein_username or not config.openprotein_password:
        raise SystemExit('请先在 backend/.env 填写 OPENPROTEIN_USERNAME 和 OPENPROTEIN_PASSWORD。')
    async with httpx.AsyncClient(trust_env=False) as http:
        adapter = OpenProteinAdapter(http, config.openprotein_username, config.openprotein_password)
        try:
            await adapter.model_metadata(await adapter.login())
        except OpenProteinError as exc:
            raise SystemExit(f'{exc} · {ERRORS[str(exc)]}') from None
        except InvalidOutput:
            raise SystemExit('OpenProtein 返回的模型或响应格式与预期不符。') from None
    print('OPENPROTEIN MODEL OK · esmfold2 · 已登录并读取模型信息，未提交预测。')


if __name__ == '__main__':
    asyncio.run(main())
