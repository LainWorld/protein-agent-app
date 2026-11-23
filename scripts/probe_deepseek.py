"""Explicit, billable live probe. Print only known labels, never HTTP bodies or secrets."""

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import secrets
import sys

import httpx
from dotenv import dotenv_values, set_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import ENV_FILE, FLASH, PublicError, settings
from app.llm_client import DeepSeek


async def probe(fill: bool) -> None:
    conf = settings()
    conf.require_llm(selecting_model=True)
    selected = conf.model or FLASH
    async with httpx.AsyncClient(trust_env=False) as http:
        ds = DeepSeek(replace(conf, model=selected), http)
        result = await ds.request('/models')
        if not any(isinstance(m, dict) and m.get('id') == selected for m in result.get('data', [])):
            raise SystemExit('FAIL: configured/candidate model not in authenticated /models; no completion sent.')
        print('PASS: authenticated /models lists the selected model' + (' (deepseek-flash).' if selected == FLASH else '.'), flush=True)
        tool = {'type': 'function', 'function': {'name': 'lookup_receipt', 'description': 'Read receipt for a ticket.',
                'parameters': {'type': 'object', 'properties': {'ticket': {'type': 'string'}}, 'required': ['ticket']}}}
        messages = [{'role': 'user', 'content': 'Use lookup_receipt for ticket demo-42. Reply with the returned receipt exactly.'}]
        first = await ds.complete(messages, [tool])
        if len(first.tool_calls) != 1:
            raise SystemExit('FAIL: expected exactly one real tool call.')
        call = first.tool_calls[0]
        if call.function.name != 'lookup_receipt' or json.loads(call.function.arguments) != {'ticket': 'demo-42'}:
            raise SystemExit('FAIL: tool name or arguments incorrect.')
        marker = 'R-' + secrets.token_hex(8)  # generated only after the model made its call
        messages.extend([first.wire(), {'role': 'tool', 'tool_call_id': call.id, 'content': json.dumps({'receipt': marker})}])
        second = await ds.complete(messages, [tool], 'none')
        if second.tool_calls or marker not in (second.content or ''):
            raise SystemExit('FAIL: final answer did not contain the fresh receipt.')
        print('PASS: auto tool name + JSON args, matched tool_call_id, fresh receipt in final answer.')
        if fill and not conf.model and not ENV_FILE.is_file():
            print('No existing backend/.env to update; set LLM_MODEL in your server environment.')
        elif fill and not conf.model and not (dotenv_values(ENV_FILE, interpolate=False).get('LLM_MODEL') or '').strip():
            ENV_FILE.chmod(0o600)
            set_key(str(ENV_FILE), 'LLM_MODEL', selected, quote_mode='never')
            print('Saved verified LLM_MODEL in the local backend/.env.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fill-model', action='store_true', help='fill a blank backend/.env model only after success')
    try:
        asyncio.run(probe(parser.parse_args().fill_model))
    except PublicError as exc:
        sys.exit(f'FAIL {exc.code}: {exc.message}')
    except (ValueError, TypeError, KeyError):
        sys.exit('FAIL: unexpected provider response.')
