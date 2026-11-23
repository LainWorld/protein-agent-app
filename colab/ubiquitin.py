"""Colab stages and a read-only verifier for the returned standalone ubiquitin run."""

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

import gemmi

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.adapters.protenix import (MODEL, OPTIONS, PACKAGE, SEED, ProtenixAdapter, ProtenixError,
                                   cif_path, cli_args, cli_input, parse_prediction)
from app.structures import InvalidOutput, verified_pdb
from resources import OBJECTS, ORIGIN

UBIQUITIN = 'MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'
SEQUENCE_SHA = '233b4b0b8c4616095bc3249f9375fc345d32af7deaef07117d0383c51d6f19aa'
TIMEOUT = 1800
FILES = ('protenix-input.json', 'prediction.cif', 'structure.pdb', 'run.json',
         'versions.json', 'hardware.json', 'resources.json', 'cli-events.jsonl')


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def check_install(root: Path):
    import torch

    if sys.version_info[:3] != (3, 11, 13) or metadata.version('protenix') != PACKAGE:
        raise SystemExit('环境版本不匹配，请重跑第 2 单元')
    if not torch.cuda.is_available():
        raise SystemExit('CUDA 不可用，请反馈 GPU、驱动和当前单元的错误')
    name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    if 'T4' not in name or capability != (7, 5) or torch.version.cuda != '12.6':
        raise SystemExit(f'T4 环境不匹配 · {name} · SM {capability} · torch CUDA {torch.version.cuda}')
    # Actually launch a CUDA kernel in the isolated interpreter.
    if torch.ones(1, device='cuda').sum().item() != 1:
        raise SystemExit('CUDA 运算检查失败')
    cli = str(Path(sys.executable).with_name('protenix'))
    version = subprocess.check_output([cli, '--version'], text=True, timeout=180)
    help_text = subprocess.check_output([cli, 'pred', '-h'], text=True, timeout=180)
    flags = ['--input', '--out_dir', '--seeds', *('--' + key for key in OPTIONS)]
    if not re.search(r'^\S+, version 2\.0\.0\s*$', version, re.M) or any(flag not in help_text for flag in flags):
        raise SystemExit('CLI 版本或 pred 参数不符')
    packages = {d.metadata['Name'].lower(): d.version for d in metadata.distributions() if d.metadata['Name']}
    write_json(root / 'versions.json', dict(python=sys.version.split()[0], packages=packages, torch_cuda=torch.version.cuda,
                                            gpu=name, capability=list(capability), cli_version=PACKAGE))
    print(f'CLI OK · Protenix {PACKAGE} · torch {torch.__version__} · CUDA {torch.version.cuda} · {name} · FP32')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_resources(receipts):
    require(set(receipts) == {row[0] for row in OBJECTS.values()}, '资源清单不完整')
    for rel, size, crc in OBJECTS.values():
        got = receipts[rel]
        require(got['bytes'] == size and got['crc64ecma'] == str(crc) and got['url'] == ORIGIN + rel
                and re.fullmatch('[0-9a-f]{64}', got['sha256']), '资源校验记录不匹配')


async def predict(root: Path, run_id: str):
    require(str(UUID(run_id)) == run_id and len(UBIQUITIN) == 76 and sha256(UBIQUITIN.encode()).hexdigest() == SEQUENCE_SHA,
            '运行编号或内置泛素不匹配')
    check_resources(json.loads((root / 'cache/resources.json').read_text()))
    adapter = ProtenixAdapter(Path(sys.executable).with_name('protenix'), root / 'cache')
    directory = root / 'runs' / run_id
    directory.mkdir(parents=True, exist_ok=False)
    # Snapshot evidence before inference. A later cell/session cannot silently substitute its environment.
    for name in ('hardware.json', 'versions.json'):
        (directory / name).write_bytes((root / name).read_bytes())
    (directory / 'resources.json').write_bytes((root / 'cache/resources.json').read_bytes())
    params = {**adapter.parameters(), 'timeout_seconds': TIMEOUT}
    run = dict(origin='standalone_colab', run_id=run_id, model=MODEL, sequence_sha256=SEQUENCE_SHA,
               parameters=params, native_path=cif_path(directory, SEED).relative_to(directory).as_posix(),
               started_at=now(), status='running')
    write_json(directory / 'run.json', run)
    try:
        async with asyncio.timeout(TIMEOUT):
            path = await adapter.predict(UBIQUITIN, directory, params)
        completed = json.loads((directory / 'cli-events.jsonl').read_text().splitlines()[-1])
        if not completed.get('cuda_selected'):
            raise ProtenixError('CLI 未报告选择 CUDA，无法验收免费 T4 推理')
        _, digest = verified_pdb(directory, path, mock=False, sequence=UBIQUITIN)
    except (ProtenixError, InvalidOutput, TimeoutError) as exc:
        reason = str(exc) or type(exc).__name__
        write_json(directory / 'run.json', {**run, 'status': 'failed', 'error': reason, 'finished_at': now()})
        events = directory / 'cli-events.jsonl'
        if events.is_file():
            print(*events.read_text().splitlines()[-2:], sep='\n')
        raise SystemExit(f'推理失败 · {reason}') from None
    write_json(directory / 'run.json', {**run, 'status': 'succeeded', 'finished_at': now(), 'pdb_sha256': digest})
    print('PREDICTION OK', run_id, flush=True)


def verify(path: Path):
    with ZipFile(path) as archive:
        names = [*FILES, 'manifest.json']
        require(sorted(archive.namelist()) == sorted(names), '归档缺少文件或有其他条目')
        require(all(0 < i.file_size <= 8_000_000 for i in archive.infolist()), '归档文件大小异常')
        data = {name: archive.read(name) for name in names}
    manifest = json.loads(data['manifest.json'])
    require(manifest == {name: sha256(data[name]).hexdigest() for name in FILES}, '归档 SHA-256 不符')
    run = json.loads(data['run.json'])
    rid = str(UUID(run['run_id']))
    params = {**OPTIONS, 'seed': SEED, 'layernorm_type': 'torch', 'package_version': PACKAGE, 'timeout_seconds': TIMEOUT}
    require(run['origin'] == 'standalone_colab' and run['run_id'] == rid and run['model'] == MODEL and
            run['parameters'] == params and run['status'] == 'succeeded' and run['sequence_sha256'] == SEQUENCE_SHA
            and run['native_path'] == cif_path(Path(rid), SEED).relative_to(rid).as_posix()
            and run['pdb_sha256'] == manifest['structure.pdb'], '运行记录不匹配')
    require(json.loads(data['protenix-input.json']) == cli_input(rid, UBIQUITIN), '官方输入不匹配')
    check_resources(json.loads(data['resources.json']))
    versions = json.loads(data['versions.json'])
    require(versions['cli_version'] == PACKAGE and versions['packages']['protenix'] == PACKAGE
            and versions['packages']['torch'].split('+')[0] == '2.7.1' and versions['torch_cuda'] == '12.6'
            and versions['python'] == '3.11.13' and versions['capability'] == [7, 5]
            and 'T4' in versions['gpu'] and 'T4' in json.loads(data['hardware.json'])['gpu'], 'T4 或环境记录不匹配')
    events = [json.loads(line) for line in data['cli-events.jsonl'].splitlines()]
    require([e['stage'] for e in events] == ['version_started', 'version_exited', 'cli_version', 'command',
                                             'prediction_started', 'prediction_exited']
            and events[1]['exit_code'] == events[-1]['exit_code'] == 0 and events[2]['package_version'] == PACKAGE
            and events[3]['argv'] == ['protenix', *cli_args(params)]
            and events[-1]['diagnostic'] is None and events[-1].get('cuda_selected') is True, 'CLI 执行记录不完整')
    require(run['started_at'] <= events[0]['utc'] <= events[-1]['utc'] <= run['finished_at'], '运行时间不匹配')
    structure = parse_prediction(data['prediction.cif'], rid, UBIQUITIN)
    headers = data['structure.pdb'].splitlines()[:3]
    require(f'REMARK 950 JOB {rid}'.encode() in headers and b'REMARK 950 MODE REAL' in headers, 'PDB 归属不符')
    copy = gemmi.read_pdb_string(data['structure.pdb'])
    require(len(copy) == 1 and len(copy[0]) == 1 and len(copy[0][0]) == 76, '导出 PDB 链或长度不符')
    for a, b in zip(structure[0][0], copy[0][0]):
        require(a.name == b.name and a.seqid == b.seqid and len(a) == len(b), 'PDB 残基不匹配')
        for atom, other in zip(a, b):
            require(atom.name == other.name and atom.element == other.element and atom.pos.dist(other.pos) <= .001,
                    'PDB 原子或坐标与原始 mmCIF 不符')
    return rid, sum(len(r) for r in structure[0][0])


def export(root: Path, rid: str):
    require(str(UUID(rid)) == rid, '运行编号无效')
    directory = root / 'runs' / rid
    paths = {name: directory / name for name in FILES}
    paths['prediction.cif'] = cif_path(directory, SEED)
    target = root / f'protenix-mini-ubiquitin-{rid}.zip'
    partial = target.with_suffix('.zip.part')
    with ZipFile(partial, 'w', ZIP_DEFLATED) as archive:
        hashes = {}
        for name, file in paths.items():
            blob = file.read_bytes()
            archive.writestr(name, blob)
            hashes[name] = sha256(blob).hexdigest()
        archive.writestr('manifest.json', json.dumps(hashes, indent=2))
    _, atoms = verify(partial)
    partial.replace(target)
    print(f'VERIFIED · 1 chain · 76 aa · {atoms} atoms · {target.name}')


if __name__ == '__main__':
    stage, location, *rest = sys.argv[1:]
    root = Path(location).resolve()
    if stage == 'check-install':
        check_install(root)
    elif stage == 'predict':
        asyncio.run(predict(root, *rest))
    elif stage == 'export':
        export(root, *rest)
    elif stage == 'verify':
        run_id, atoms = verify(root)
        print(f'VERIFIED · standalone_colab · {run_id} · 1 chain · 76 aa · {atoms} atoms')
    else:
        raise SystemExit('use check-install, predict, export or verify')
