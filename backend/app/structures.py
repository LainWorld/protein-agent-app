"""Validate exactly the bytes that can be served, from a server-owned job path."""

import hashlib
import math
from pathlib import Path

import gemmi


class InvalidOutput(ValueError):
    pass


def verified_pdb(directory: Path, path: Path, *, mock: bool, digest: str | None = None,
                 sequence: str | None = None) -> tuple[bytes, str]:
    expected = directory / 'structure.pdb'
    if (path != expected or directory.is_symlink() or directory.parent.is_symlink() or path.is_symlink()
            or not path.is_file() or not 0 < path.stat().st_size <= 8_000_000):
        raise InvalidOutput('missing or misplaced output')
    blob = path.read_bytes()
    checksum = hashlib.sha256(blob).hexdigest()
    if digest is not None and checksum != digest:
        raise InvalidOutput('changed output')
    headers = [line.rstrip() for line in blob.splitlines()[:5]]
    if f'REMARK 950 JOB {directory.name}'.encode() not in headers:
        raise InvalidOutput('wrong job')
    if not mock and b'REMARK 950 MODE REAL' not in headers:
        raise InvalidOutput('wrong prediction mode')
    try:
        # PDB readers can coerce malformed numeric fields to zero. Check raw
        # coordinates first, then use Gemmi to distinguish protein from water/ligands.
        for line in blob.splitlines():
            if line.startswith((b'ATOM  ', b'HETATM')):
                if not all(math.isfinite(float(line[i:i+8])) for i in (30, 38, 46)):
                    raise ValueError()
        structure = gemmi.read_pdb_string(blob)
        if not mock:
            if len(structure) != 1 or len(structure[0]) != 1:
                raise ValueError()
            residues = structure[0][0]
            if (''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in residues) != sequence
                    or any(r.find_atom('CA', '*') is None for r in residues)):
                raise ValueError()
        if not any(r.find_atom('CA', '*') is not None and gemmi.find_tabulated_residue(r.name).is_amino_acid()
                   for m in structure for c in m for r in c):
            raise ValueError()
    except (RuntimeError, ValueError, OverflowError):
        raise InvalidOutput('no valid protein coordinates') from None
    return blob, checksum
