"""Two explicit mock routes; neither imports a model or accepts a path from chat."""

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from app.config import BACKEND
from app.schemas import FoldModel

FIXTURE = BACKEND.parent / 'examples' / 'fixtures' / '1ubq.pdb'
SOURCE = 'https://www.rcsb.org/structure/1UBQ'
FIXTURE_SHA = 'd4a6812d8951cf6594e6a0763f089e35f5a80b62acb3c117b2c5565228a7b161'
VERSION = 'mock-1UBQ-v1'


@dataclass(frozen=True)
class MockAdapter:
    model: FoldModel
    fixture: Path = FIXTURE
    delay: float = 3.0
    version = VERSION

    def parameters(self) -> dict:
        return {'fixture_id': '1UBQ', 'source': SOURCE, 'fixture_sha256': FIXTURE_SHA,
                'mock_delay_seconds': self.delay}

    async def predict(self, sequence: str, directory: Path, parameters: dict) -> Path:
        # A short cancellable delay makes polling visible. It is not inference time.
        await asyncio.sleep(parameters['mock_delay_seconds'])
        source = self.fixture.read_bytes()
        if sha256(source).hexdigest() != FIXTURE_SHA:
            raise ValueError('unrecognized fixture')
        header, body = source.split(b'\n', 1)
        note = (f'REMARK 950 MOCK EXAMPLE ONLY. NOT A PREDICTION FOR THE INPUT SEQUENCE.\n'
                f'REMARK 950 SOURCE RCSB PDB 1UBQ. ROUTE {self.model.upper()}.\n'
                f'REMARK 950 JOB {directory.name}\n').encode('ascii')
        output = directory / 'structure.pdb'
        output.write_bytes(header + b'\n' + note + body)
        return output
