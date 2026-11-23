#!/usr/bin/env python3
"""Executable test double used only inside pytest's temporary directories."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).parent
case = (root / 'case').read_text()
if sys.argv[1:] == ['--version']:
    print('protenix, version ' + ('1.0.0' if case == 'version' else '2.0.0'))
    sys.exit(0)

args = sys.argv[1:]
assert args[0] == 'pred'
flags = {key.removeprefix('--'): value for key, value in zip(args[1::2], args[2::2])}
assert flags == dict(input='protenix-input.json', out_dir='output', seeds='101', model_name='protenix_mini_default_v0.5.0',
                     use_msa='false', use_template='false', use_rna_msa='false', cycle='4', step='5', sample='1', dtype='fp32',
                     triatt_kernel='torch', trimul_kernel='torch', enable_fusion='false', enable_tf32='false')
assert os.environ['LAYERNORM_TYPE'] == 'torch'
assert 'LLM_API_KEY' not in os.environ and 'ESMFOLD2_API_KEY' not in os.environ
row, = json.loads(Path(flags['input']).read_text())
jid = row['name']
assert jid == Path.cwd().name and row['sequences'] == [{'proteinChain': {'count': 1, 'sequence': (root/'sequence').read_text()}}]
print('upstream-private-string-for-redaction')
print('LOCAL_RANK: 0 - CUDA_VISIBLE_DEVICES: [0]')  # Official log shape, emitted by this test double only.
if case == 'timeout':
    # Parent and child both own the pipe. A leaked child would write after the job timed out.
    child = ('import pathlib, time\nwhile not pathlib.Path("release-child").exists(): time.sleep(.02)\n'
             'pathlib.Path("leaked-child").touch()')
    subprocess.Popen([sys.executable, '-c', child])
    Path('spawned').touch()
    time.sleep(10)
if case == 'oom':
    print('torch.OutOfMemoryError: CUDA out of memory')
    sys.exit(1)
if case == 'missing':
    sys.exit(0)
if case == 'reported':
    Path('output/ERR').mkdir()
    Path('output/ERR/error.txt').write_text('sample failed')
    sys.exit(0)
seed = '100' if case == 'wrong_seed' else '101'
folder = Path('output') / jid / ('seed_' + seed) / 'predictions'
folder.mkdir(parents=True)
out = folder / (jid + '_sample_0.cif')
if case == 'symlink':
    out.symlink_to(root/'reference.cif')
else:
    reference = (root/'reference.cif').read_text().replace('RUNID', jid)
    if case == 'wrong_job':
        reference = reference.replace('_entry.id ' + jid, '_entry.id 00000000-0000-4000-b000-000000000001')
    if case == 'wrong_block':
        reference = reference.replace('data_' + jid, 'data_foreign')
    if case == 'corrupt':
        reference = 'data_broken\nloop_\n'
    if case == 'empty':
        reference = ''
    out.write_text(reference)
# A valid-looking CIF must be ignored if the command reported failure.
sys.exit(17 if case == 'nonzero' else 0)
