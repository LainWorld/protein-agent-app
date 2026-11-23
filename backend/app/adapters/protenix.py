"""One pinned official Mini CLI invocation per job. The backend never imports torch."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal

import gemmi

from app.structures import InvalidOutput

MODEL = 'protenix_mini_default_v0.5.0'
PACKAGE = '2.0.0'
SEED = 101
# Names and value types are the Click options in the PyPI 2.0.0 wheel.
OPTIONS = dict(model_name=MODEL, use_msa=False, use_template=False, use_rna_msa=False,
               cycle=4, step=5, sample=1, dtype='fp32', triatt_kernel='torch',
               trimul_kernel='torch', enable_fusion=False, enable_tf32=False)


class ProtenixError(RuntimeError):
    """Only fixed public error codes cross the process boundary."""


def cli_input(run_id: str, sequence: str) -> list:
    return [{'name': run_id, 'sequences': [{'proteinChain': {'sequence': sequence, 'count': 1}}]}]


def cli_args(parameters: dict) -> list[str]:
    args = ['pred', '--input', 'protenix-input.json', '--out_dir', 'output', '--seeds', str(parameters['seed'])]
    for key in OPTIONS:
        value = parameters[key]
        args.extend(['--' + key, str(value).lower() if isinstance(value, bool) else str(value)])
    return args


def cif_path(directory: Path, seed: int) -> Path:
    return directory / 'output' / directory.name / f'seed_{seed}' / 'predictions' / f'{directory.name}_sample_0.cif'


def parse_prediction(blob: bytes, run_id: str, sequence: str) -> gemmi.Structure:
    """Check the identity embedded by the official writer, including for equal-sequence jobs."""
    try:
        block = gemmi.cif.read_string(blob.decode('utf-8')).sole_block()
        entry = block.find_value('_entry.id')
        if not entry or gemmi.cif.as_string(entry) != run_id or block.name != f'{run_id}_sample_0_predicted_by_protenix':
            raise ValueError('sample identifier')
        xyz = block.find(['_atom_site.Cartn_x', '_atom_site.Cartn_y', '_atom_site.Cartn_z'])
        if not len(xyz) or any(not -999.999 <= float(v) <= 9999.999 for row in xyz for v in row):
            raise ValueError('coordinates outside finite PDB range')
        structure = gemmi.make_structure_from_block(block)
        if len(structure) != 1 or len(structure[0]) != 1:
            raise ValueError('model or chain count')
        chain = structure[0][0]
        if ''.join(gemmi.find_tabulated_residue(r.name).one_letter_code for r in chain) != sequence:
            raise ValueError('sequence')
        for residue in chain:
            ca = residue.find_atom('CA', '*')
            if ca is None or ca.element.name != 'C':
                raise ValueError('missing alpha carbon')
        if sum(len(r) for r in chain) != len(xyz):
            raise ValueError('unparsed atoms')
    except (RuntimeError, ValueError, IndexError, OverflowError) as exc:
        raise InvalidOutput('invalid Protenix mmCIF') from exc
    return structure


def export_pdb(directory: Path, sequence: str, seed: int) -> Path:
    cif = cif_path(directory, seed)
    if (directory.is_symlink() or cif.resolve() != directory.resolve() / cif.relative_to(directory)
            or not cif.is_file() or not 0 < cif.stat().st_size <= 8_000_000):
        raise InvalidOutput('missing or misplaced Protenix sample')
    structure = parse_prediction(cif.read_bytes(), directory.name, sequence)
    pdb = directory / 'structure.pdb'
    with pdb.open('x', encoding='ascii') as stream:
        stream.write(f'REMARK 950 JOB {directory.name}\nREMARK 950 MODE REAL\nREMARK 950 {MODEL} SEED {seed}\n')
        stream.write(structure.make_minimal_pdb())
    return pdb


def event(directory: Path, stage: str, **facts) -> None:
    # Keep process output private. Only structured facts from this module enter the portable log.
    with (directory / 'cli-events.jsonl').open('a', encoding='utf-8') as stream:
        print(json.dumps(dict(utc=datetime.now(timezone.utc).isoformat(), stage=stage, **facts)), file=stream)


def diagnostic(output: bytes) -> str | None:
    message = output.lower()
    if b'out of memory' in message or b'outofmemoryerror' in message:
        return 'protenix_oom'
    if any(term in message for term in (b'no nvidia driver', b'cuda error', b'cuda is not available', b'no kernel image')):
        return 'protenix_cuda'
    if any(term in message for term in (b'urlopen error', b'http error', b'download model checkpoint failed')):
        return 'protenix_download'
    if b'run inference failed:' in message:
        return 'protenix_execution'
    return None


async def invoke(executable: Path, args: list[str], directory: Path, env: dict, stage: str) -> bytes:
    try:
        process = await asyncio.create_subprocess_exec(str(executable), *args, cwd=directory, env=env,
                        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        raise ProtenixError('protenix_cli') from exc
    tail = b''
    reason = None
    observed = {}
    try:
        event(directory, stage + '_started')
        while chunk := await process.stdout.read(8192):
            tail = (tail + chunk)[-16384:]
            reason = diagnostic(tail) or reason
            if b' - CUDA_VISIBLE_DEVICES: [' in tail:
                observed['cuda_selected'] = True
            if timing := re.search(rb'Model forward time: (\d+\.\d+)s', tail):
                observed['forward_seconds'] = float(timing[1])
            if counts := re.search(rb'N_asym (\d+), N_token (\d+), N_atom (\d+), N_msa (\d+)\b', tail):
                observed.update(zip(('chains', 'tokens', 'atoms', 'msa_depth'), map(int, counts.groups())))
        code = await process.wait()
    except BaseException:
        # A timed-out CLI may own CUDA workers with inherited pipe handles.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.communicate()
        event(directory, stage + '_interrupted')
        raise
    event(directory, stage + '_exited', exit_code=code, diagnostic=reason, **observed)
    if code or reason:
        raise ProtenixError(reason or 'protenix_execution')
    return tail


@dataclass(frozen=True)
class ProtenixAdapter:
    executable: Path
    resource_dir: Path
    version = MODEL

    def parameters(self) -> dict:
        return {'package_version': PACKAGE, 'seed': SEED, 'layernorm_type': 'torch', **OPTIONS}

    async def predict(self, sequence: str, directory: Path, parameters: dict) -> Path:
        # JobService creates a fresh private directory. Exclusive creation rejects stale samples on retry.
        with (directory / 'protenix-input.json').open('x', encoding='utf-8') as stream:
            json.dump(cli_input(directory.name, sequence), stream, indent=2)
        (directory / 'output').mkdir()
        env = {k: os.environ[k] for k in ('HOME', 'PATH', 'TMPDIR', 'LANG', 'LD_LIBRARY_PATH', 'CUDA_HOME',
                                          'CUDA_VISIBLE_DEVICES', 'CUDA_PATH') if k in os.environ}
        env.update(PATH=str(self.executable.parent) + os.pathsep + env.get('PATH', os.defpath),
                   PROTENIX_ROOT_DIR=str(self.resource_dir), LAYERNORM_TYPE=parameters['layernorm_type'],
                   PYTHONNOUSERSITE='1')
        version = await invoke(self.executable, ['--version'], directory, env, 'version')
        match = re.search(rb'^\S+, version ([0-9.]+)\s*$', version, re.MULTILINE)
        actual = match[1].decode() if match else None
        event(directory, 'cli_version', package_version=actual)
        if actual != PACKAGE:
            raise ProtenixError('protenix_version')
        args = cli_args(parameters)
        event(directory, 'command', argv=['protenix', *args], layernorm_type=parameters['layernorm_type'])
        await invoke(self.executable, args, directory, env, 'prediction')
        # The upstream runner catches per-sample failures and can still exit with code zero.
        errors = directory / 'output' / 'ERR'
        if errors.exists() and any(errors.iterdir()):
            raise ProtenixError('protenix_execution')
        return export_pdb(directory, sequence, parameters['seed'])
