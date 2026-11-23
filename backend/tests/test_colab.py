"""Exercise the deliverable without GPU or network. All run metadata below is test data."""

import asyncio
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from uuid import uuid4
from zipfile import ZipFile

import pytest

from test_jobs import UBQ, install_cli_double

PROJECT = Path(__file__).resolve().parents[2]
sys.path.extend([str(PROJECT / 'colab'), str(PROJECT / 'scripts')])
import build_protenix_colab as builder
import resources
import ubiquitin


def test_single_notebook_matches_sources_and_has_five_executable_stages():
    nb = json.loads(builder.NOTEBOOK.read_bytes())
    assert nb == builder.notebook()
    code = {c['id']: ''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code'}
    assert list(code) == ['gpu', 'install', 'assets', 'predict', 'export']
    for stage, source in code.items():
        compile(source, stage, 'exec')
    encoded = re.search(r"b64decode\('''([A-Za-z0-9+/=\n]+)'''\)", code['install'])[1]
    blob = base64.b64decode(encoded)
    assert hashlib.sha256(blob).hexdigest() in code['install']
    with ZipFile(io.BytesIO(blob)) as archive:
        assert set(archive.namelist()) == set(builder.SUPPORT)
        for name in archive.namelist():
            assert archive.read(name) == (PROJECT / name).read_bytes()
            assert Path(name).suffix in {'.py', '.lock'}
    assert ubiquitin.UBIQUITIN == UBQ and len(UBQ) == 76
    assert UBQ in (PROJECT / 'examples/fixtures/README.md').read_text()


def test_resource_crc_resume_and_detect_changed_cache(tmp_path, monkeypatch):
    # Published CRC-64/XZ check vector. Exercise the same incremental liblzma calls as the large objects.
    blob = b'123456789'
    crc = 0x995DC9BBDF1939FA
    part = tmp_path / 'cache.bin.part'
    part.write_bytes(blob[:3])
    seen = []

    def respond(req, timeout):
        seen.append(req.get_header('Range'))
        response = io.BytesIO(blob[3:] if seen[-1] else blob)
        response.status = 206 if seen[-1] else 200
        response.headers = {'Content-Range': 'bytes 3-8/9'}
        return response

    monkeypatch.setattr(resources, 'urlopen', respond)
    got = resources.download(tmp_path, 'cache.bin', len(blob), crc)
    assert got == {'bytes': 9, 'crc64ecma': str(crc), 'sha256': hashlib.sha256(blob).hexdigest()}
    assert resources.download(tmp_path, 'cache.bin', len(blob), crc) == got and seen == ['bytes=3-']
    (tmp_path / 'cache.bin').write_bytes(blob[::-1])
    assert resources.download(tmp_path, 'cache.bin', len(blob), crc) == got and seen == ['bytes=3-', None]
    with pytest.raises(SystemExit, match='CRC64'):
        resources.download(tmp_path, 'bad.bin', len(blob), crc - 1)
    assert not (tmp_path / 'bad.bin').exists()


def test_standalone_export_verifier_and_job_mismatch(tmp_path, monkeypatch):
    cli = Path(install_cli_double(tmp_path, 'success')['protenix_executable'])
    monkeypatch.setattr(sys, 'executable', str(cli.with_name('python')))
    root = tmp_path / 'standalone'
    (root / 'cache').mkdir(parents=True)
    receipts = {rel: dict(bytes=size, crc64ecma=str(crc), url=resources.ORIGIN + rel, sha256='0'*64)
                for rel, size, crc in resources.OBJECTS.values()}
    ubiquitin.write_json(root / 'cache/resources.json', receipts)
    ubiquitin.write_json(root / 'hardware.json', {'gpu': 'T4 test double'})
    ubiquitin.write_json(root / 'versions.json', dict(python='3.11.13', capability=[7,5], gpu='T4 test double',
            cli_version='2.0.0', torch_cuda='12.6', packages={'torch':'2.7.1', 'protenix':'2.0.0'}))
    rid = str(uuid4())
    asyncio.run(ubiquitin.predict(root, rid))
    # The same invocation cannot reuse the previous output.
    with pytest.raises(FileExistsError):
        asyncio.run(ubiquitin.predict(root, rid))
    ubiquitin.export(root, rid)
    path = root / f'protenix-mini-ubiquitin-{rid}.zip'
    assert ubiquitin.verify(path) == (rid, 602)
    with ZipFile(path) as archive:
        data = {name: archive.read(name) for name in archive.namelist()}
    assert not any(b'upstream-private-string' in blob for blob in data.values())
    data['prediction.cif'] = data['prediction.cif'].replace(rid.encode(), str(uuid4()).encode())
    for rebuild_digests in (False, True):
        if rebuild_digests:
            data['manifest.json'] = json.dumps({n: hashlib.sha256(data[n]).hexdigest() for n in ubiquitin.FILES}).encode()
        other = root / 'tampered.zip'
        with ZipFile(other, 'w') as archive:
            for name, blob in data.items():
                archive.writestr(name, blob)
        with pytest.raises(ValueError):
            ubiquitin.verify(other)
