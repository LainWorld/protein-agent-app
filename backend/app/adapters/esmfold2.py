"""Single-chain ESMFold2 Fast via Biohub's synchronous JSON fold endpoint."""

from dataclasses import dataclass, field
import json
from pathlib import Path

import gemmi
import httpx

from app.config import BIOHUB_URL, ESMFOLD2_FAST
from app.structures import InvalidOutput

FOLD_URL = BIOHUB_URL + '/api/v1/fold'
# Order of the 37 slots in Biohub/esm's esm.utils.residue_constants.atom_types.
ATOM37 = (
    'N CA C CB O CG CG1 CG2 OG OG1 SG CD CD1 CD2 ND1 ND2 OD1 OD2 SD CE CE1 '
    'CE2 CE3 NE NE1 NE2 OE1 OE2 CH2 NH1 NH2 OH CZ CZ2 CZ3 NZ OXT'
).split()


class BiohubError(Exception):
    """Only local error codes may be persisted or returned to chat."""


def write_fold(data: dict, sequence: str, directory: Path) -> Path:
    if not isinstance(data, dict):
        raise InvalidOutput('expected fold object')
    # The official client also unwraps the platform gateway's data envelope.
    fold = data.get('data', data)
    if not isinstance(fold, dict) or fold.get('model') != ESMFOLD2_FAST:
        raise InvalidOutput('unexpected model')
    if fold.get('sequence', sequence) != sequence:
        raise InvalidOutput('wrong returned sequence')
    positions = fold.get('coordinates')
    if not isinstance(positions, list) or len(positions) != len(sequence):
        raise InvalidOutput('wrong number of residues')

    chain = gemmi.Chain('A')
    for index, (letter, row) in enumerate(zip(sequence, positions), start=1):
        if not isinstance(row, list) or len(row) != len(ATOM37):
            raise InvalidOutput('expected atom37 coordinates')
        residue = gemmi.Residue()
        residue.name = gemmi.expand_one_letter(letter, gemmi.ResidueKind.AA)
        residue.seqid = gemmi.SeqId(index, ' ')
        residue.het_flag = 'A'
        for name, xyz in zip(ATOM37, row):
            if xyz == [None, None, None]:
                continue
            # Bounds also ensure the values fit three fixed-width PDB 8.3 fields.
            if (not isinstance(xyz, list) or len(xyz) != 3 or
                    not all(type(v) in (float, int) and -999.999 <= v <= 9999.999 for v in xyz)):
                raise InvalidOutput('invalid atom coordinates')
            atom = gemmi.Atom()
            atom.name, atom.element = name, gemmi.Element(name[0])
            atom.pos = gemmi.Position(*xyz)
            atom.occ, atom.b_iso = 1.0, 0.0
            residue.add_atom(atom)
        if residue.find_atom('CA', '*') is None:
            raise InvalidOutput('missing protein alpha carbon')
        chain.add_residue(residue)

    structure = gemmi.Structure()
    model = gemmi.Model(1)
    model.add_chain(chain)
    structure.add_model(model)
    structure.raw_remarks = [f'REMARK 950 JOB {directory.name}', 'REMARK 950 MODE REAL', f'REMARK 950 BIOHUB {ESMFOLD2_FAST}',
                             'REMARK 950 B FACTORS UNUSED. THIS EXPORT CONTAINS PREDICTED COORDINATES.']
    options = gemmi.PdbWriteOptions()
    options.cryst1_record = False
    path = directory / 'structure.pdb'
    path.write_text(structure.make_pdb_string(options), encoding='ascii')
    return path


@dataclass(frozen=True)
class ESMFold2Adapter:
    http: httpx.AsyncClient = field(repr=False)
    token: str = field(repr=False)
    version = ESMFOLD2_FAST

    def parameters(self) -> dict:
        return {'endpoint': FOLD_URL, 'disable_cache': True, 'accept': 'application/json',
                'fold_options': {'model': self.version, 'msa': None}}

    async def predict(self, sequence: str, directory: Path, parameters: dict) -> Path:
        payload = {**parameters['fold_options'], 'sequence': sequence}
        headers = {'Authorization': f'Bearer {self.token}', 'Accept': parameters['accept'],
                   'X-Disable-Cache': 'true'}
        try:
            async with self.http.stream('POST', FOLD_URL, headers=headers, json=payload, follow_redirects=False,
                                        timeout=parameters['timeout_seconds']) as response:
                if response.status_code != 200:
                    codes = {401: 'biohub_auth', 402: 'biohub_credits', 403: 'biohub_access',
                             422: 'biohub_input', 429: 'biohub_rate_limit', 451: 'biohub_region',
                             408: 'timeout', 504: 'timeout'}
                    raise BiohubError(codes.get(response.status_code, 'biohub_upstream'))
                if response.headers.get('Content-Type', '').partition(';')[0].strip().lower() != 'application/json':
                    raise InvalidOutput('expected JSON response')
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 8_000_000:
                        raise InvalidOutput('oversize response')
                    body.extend(chunk)
        except httpx.TimeoutException:
            raise BiohubError('timeout') from None
        except httpx.RequestError:
            raise BiohubError('biohub_connection') from None
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            raise InvalidOutput('invalid fold JSON') from None
        return write_fold(data, sequence, directory)
