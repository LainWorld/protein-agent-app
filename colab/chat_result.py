"""Run one task exported by the Mac chat, inside the notebook's isolated interpreter."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import UUID

from app.adapters.protenix import MODEL, SEED, ProtenixAdapter, ProtenixError, cif_path
from app.structures import InvalidOutput


async def run(root, job_id, sequence):
    assert str(UUID(job_id)) == job_id
    directory = root / 'mac-chat' / job_id
    directory.mkdir(parents=True, exist_ok=False)
    receipt = dict(job_id=job_id, sequence=sequence, model=MODEL, seed=SEED)
    adapter = ProtenixAdapter(Path(sys.executable).with_name('protenix'), root / 'cache')
    try:
        async with asyncio.timeout(1800):
            await adapter.predict(sequence, directory, adapter.parameters())
        events = [json.loads(line) for line in (directory/'cli-events.jsonl').read_text().splitlines()]
        if not events[-1].get('cuda_selected'):
            raise ProtenixError('protenix_cuda')
        cif = cif_path(directory, SEED).read_bytes()
        receipt.update(status='succeeded', cif=cif.decode(), sha256=sha256(cif).hexdigest(), events=events)
    except (TimeoutError, ProtenixError, InvalidOutput) as exc:
        reason = 'timeout' if isinstance(exc, TimeoutError) else 'invalid_output' if isinstance(exc, InvalidOutput) else str(exc)
        receipt.update(status='failed', error=reason)
    path = directory / f'protenix-result-{job_id}.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(receipt))
    temporary.replace(path)
    print(receipt['status'], job_id, receipt.get('error', ''))


if __name__ == '__main__':
    asyncio.run(run(Path(sys.argv[1]), sys.argv[2], sys.argv[3]))
