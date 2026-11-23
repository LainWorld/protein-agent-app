"""OpenProtein production REST API, full ESMFold2, one single-sequence chain."""

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
from uuid import UUID

import gemmi
import httpx

from app.structures import InvalidOutput

API = 'https://api.openprotein.ai/api/v1'
MODEL = 'esmfold2'
POLL_SECONDS = 2


class OpenProteinError(Exception):
    """Only fixed local codes cross the adapter boundary."""


def check_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    codes = {400: 'openprotein_input', 401: 'openprotein_auth', 402: 'openprotein_quota',
             403: 'openprotein_access', 404: 'openprotein_missing', 422: 'openprotein_input',
             429: 'openprotein_limit', 451: 'openprotein_access', 408: 'timeout', 504: 'timeout'}
    raise OpenProteinError(codes.get(response.status_code, 'openprotein_upstream'))


def object_response(body: bytes) -> dict:
    try:
        result = json.loads(body)
    except (ValueError, RecursionError):
        raise InvalidOutput('invalid OpenProtein JSON') from None
    if not isinstance(result, dict):
        raise InvalidOutput('expected OpenProtein object')
    return result


@dataclass(frozen=True)
class OpenProteinAdapter:
    http: httpx.AsyncClient = field(repr=False)
    username: str = field(repr=False)
    password: str = field(repr=False)
    version = MODEL

    def parameters(self) -> dict:
        return dict(provider='openprotein', endpoint=API + '/fold/models/' + MODEL,
                    msa_id=None, diffusion_samples=1, num_recycles=3, num_steps=50, seed=0)

    async def request(self, method: str, path: str, *, limit: int = 64_000, **kwargs) -> bytes:
        try:
            async with self.http.stream(method, API + path, follow_redirects=False, timeout=30, **kwargs) as response:
                check_status(response)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > limit:
                        raise InvalidOutput('oversize OpenProtein response')
                    data.extend(chunk)
                return bytes(data)
        except httpx.TimeoutException:
            raise OpenProteinError('timeout') from None
        except httpx.RequestError:
            raise OpenProteinError('openprotein_connection') from None

    async def login(self) -> dict:
        body = await self.request('POST', '/auth/login', headers={'X-Token-Delivery': 'body'},
                                  data={'username': self.username, 'password': self.password})
        token = object_response(body).get('access_token')
        if not isinstance(token, str) or not token or not token.isascii() or not token.isprintable() or ' ' in token:
            raise OpenProteinError('openprotein_auth')
        return {'Authorization': 'Bearer ' + token}

    async def model_metadata(self, headers: dict) -> dict:
        metadata = object_response(await self.request('GET', '/fold/models/' + MODEL, headers=headers))
        if metadata.get('model_id') != MODEL:
            raise InvalidOutput('unexpected OpenProtein model')
        return metadata

    async def predict(self, sequence: str, directory: Path, parameters: dict) -> Path:
        headers = await self.login()
        metadata = await self.model_metadata(headers)
        maximum = metadata.get('max_sequence_length')
        if isinstance(maximum, int) and maximum > 0 and len(sequence) > maximum:
            raise OpenProteinError('openprotein_input')
        protein = dict(id='A', sequence=sequence, msa_id=parameters['msa_id'])
        options = {k: parameters[k] for k in ('diffusion_samples', 'num_recycles', 'num_steps', 'seed')}
        receipt = object_response(await self.request('POST', '/fold/models/' + MODEL, headers=headers,
                                                     json={'sequences': [[{'protein': protein}]], **options}))
        try:
            remote_id = str(UUID(receipt['job_id']))
        except (KeyError, TypeError, ValueError, AttributeError):
            raise InvalidOutput('invalid remote job ID') from None
        (directory / 'openprotein-job.json').write_text(json.dumps(
            dict(job_id=remote_id, local_job_id=directory.name, model_id=MODEL), indent=2))

        async def get(path: str, **kwargs) -> bytes:
            nonlocal headers
            try:
                return await self.request('GET', path, headers=headers, **kwargs)
            except OpenProteinError as exc:
                if str(exc) != 'openprotein_auth':
                    raise
                headers = await self.login()
                return await self.request('GET', path, headers=headers, **kwargs)

        while True:
            state = object_response(await get('/jobs/' + remote_id))
            if state.get('job_id') != remote_id:
                raise InvalidOutput('wrong remote status')
            status = state.get('status')
            if status == 'SUCCESS':
                break
            if status in ('FAILURE', 'CANCELED'):
                raise OpenProteinError('openprotein_execution')
            if status not in ('PENDING', 'RUNNING', 'RETRYING'):
                raise InvalidOutput('unknown remote status')
            await asyncio.sleep(POLL_SECONDS)

        fold = object_response(await get('/fold/' + remote_id))
        if fold.get('job_id') != remote_id or fold.get('model_id') != MODEL:
            raise InvalidOutput('wrong fold metadata')
        blob = await get(f'/fold/{remote_id}/0', params={'format': 'mmcif'}, limit=8_000_000)
        try:
            block = gemmi.cif.read_string(blob.decode()).sole_block()
            xyz = block.find(['_atom_site.Cartn_x', '_atom_site.Cartn_y', '_atom_site.Cartn_z'])
            if not len(xyz) or any(not -999.999 <= float(v) <= 9999.999 for row in xyz for v in row):
                raise ValueError('coordinates outside PDB range')
            structure = gemmi.make_structure_from_block(block)
            if len(structure) != 1 or len(structure[0]) != 1 or structure[0].count_atom_sites() != len(xyz):
                raise ValueError('incomplete or multichain result')
            pdb = structure.make_minimal_pdb().encode('ascii')
        except (RuntimeError, ValueError, IndexError, OverflowError):
            raise InvalidOutput('invalid OpenProtein mmCIF') from None
        (directory / 'openprotein.cif').write_bytes(blob)
        path = directory / 'structure.pdb'
        remarks = f'REMARK 950 JOB {directory.name}\nREMARK 950 MODE REAL\nREMARK 950 OPENPROTEIN {MODEL} {remote_id}\n'
        path.write_bytes(remarks.encode('ascii') + pdb)
        # JobService verifies the exported bytes and every submitted residue before publication.
        return path
