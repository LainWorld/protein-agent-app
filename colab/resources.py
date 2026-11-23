"""Download the five Mini objects from the pinned wheel's public URL map."""

import ctypes
import ctypes.util
import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ORIGIN = 'https://protenix.tos-cn-beijing.volces.com/'
# Public TOS object lengths and x-tos-hash-crc64ecma headers, checked 2026-11-20.
# Multipart ETags on this host are not whole-file MD5 checksums.
OBJECTS = {
    'protenix_mini_default_v0.5.0': ('checkpoint/protenix_mini_default_v0.5.0.pt', 537049294, 10972385948284009591),
    'ccd_components_file': ('common/components.cif', 490777362, 15584011929812638962),
    'ccd_components_rdkit_mol_file': ('common/components.cif.rdkit_mol.pkl', 142498117, 8545945069051395908),
    'pdb_cluster_file': ('common/clusters-by-entity-40.txt', 21699572, 12223273734315499485),
    'obsolete_release_data_csv': ('common/obsolete_release_date.csv', 134716, 14600707826131585206),
}


def checksum(path: Path, size: int, crc: int) -> dict:
    if path.stat().st_size != size:
        raise ValueError('文件大小与官方记录不符')
    # liblzma (XZ Utils) uses the same reflected ECMA polynomial and initial/final XOR as TOS.
    update = ctypes.CDLL(ctypes.util.find_library('lzma')).lzma_crc64
    update.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint64]
    update.restype = ctypes.c_uint64
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            total = update(chunk, len(chunk), total)
    if total != crc:
        raise ValueError('CRC64 与官方记录不符')
    return {'bytes': size, 'crc64ecma': str(total), 'sha256': digest.hexdigest()}


def download(root: Path, rel: str, size: int, crc: int) -> dict:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        try:
            return checksum(dest, size, crc)
        except ValueError:
            pass
    part = dest.with_suffix(dest.suffix + '.part')
    for attempt in range(1, 4):
        offset = part.stat().st_size if part.exists() else 0
        try:
            if offset < size:
                request = Request(ORIGIN + rel, headers={'Range': f'bytes={offset}-'} if offset else {})
                with urlopen(request, timeout=90) as response:
                    if response.status == 206:
                        if response.headers.get('Content-Range') != f'bytes {offset}-{size-1}/{size}':
                            raise ValueError('服务器返回的分段范围不符')
                    elif response.status == 200:
                        offset = 0
                    else:
                        raise ValueError(f'HTTP {response.status}')
                    with part.open('ab' if offset else 'wb') as stream:
                        while chunk := response.read(1 << 20):
                            if stream.tell() + len(chunk) > size:
                                raise ValueError('下载超过官方对象大小')
                            stream.write(chunk)
            receipt = checksum(part, size, crc)
            part.replace(dest)
            return receipt
        except (OSError, ValueError, URLError, HTTPException) as exc:
            if part.exists() and part.stat().st_size >= size:
                part.unlink()
            detail = f'HTTP {exc.code}' if isinstance(exc, HTTPError) else str(exc)
            print(f'{rel} · 尝试 {attempt}/3 · {detail}', flush=True)
            if attempt == 3:
                raise SystemExit(f'资源下载/校验失败 · {rel} · {detail}') from None


def prepare(root: Path):
    from protenix.web_service.dependency_url import URL
    receipts = {}
    for key, (rel, size, crc) in OBJECTS.items():
        if URL[key] != ORIGIN + rel:
            raise SystemExit(f'安装包的资源映射不匹配 · {key}')
        print(f'检查 {rel} ({size:,} bytes)', flush=True)
        receipts[rel] = {'url': URL[key], **download(root, rel, size, crc)}
        print('OK', rel, receipts[rel]['sha256'], flush=True)
    (root / 'resources.json').write_text(json.dumps(receipts, indent=2))
    print('ASSETS OK · 5/5')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
