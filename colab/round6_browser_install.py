"""Install the pinned Linux browser driver and headless Chromium after the job is checkpointed."""

import base64
from hashlib import sha256, sha512
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen

NODE = '24.22.3'
PLAYWRIGHT = '1.62.1'
NODE_SHA = '4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb'
PW_SHA = 'wPYSwEBJY9GHraISXqyqtx0na0LpO3XEX7jNDhntbex7tzUS7kLnZsOlFruFJB4Hi/rhDMjXGqHewDZ68nYZVw=='


def fetch(url, path, hash_fn, expected):
    checksum = hash_fn()
    with urlopen(url, timeout=90) as response, path.open('wb') as stream:
        while chunk := response.read(1 << 20):
            stream.write(chunk)
            checksum.update(chunk)
    if checksum.digest() != expected:
        raise ValueError('浏览器依赖下载的摘要不符 · '+path.name)


def install(work):
    tools = work/'browser-tools'
    tools.mkdir(exist_ok=True)
    node = tools/'node'
    modules = Path(__file__).resolve().parents[1]/'frontend/node_modules'
    modules.mkdir(exist_ok=True)
    driver = modules/'playwright-core'
    with tempfile.TemporaryDirectory(dir=tools) as temp:
        folder = Path(temp)
        if not node.exists():
            name = f'node-v{NODE}-linux-x64'
            archive = folder/'node.tar.xz'
            fetch(f'https://nodejs.org/dist/v{NODE}/{name}.tar.xz', archive, sha256, bytes.fromhex(NODE_SHA))
            with tarfile.open(archive) as tar, tar.extractfile(name+'/bin/node') as src, (folder/'node').open('wb') as dest:
                shutil.copyfileobj(src,dest)
            (folder/'node').chmod(0o755)
            (folder/'node').replace(node)
        if not driver.exists():
            archive = folder/'driver.tgz'
            fetch(f'https://registry.npmjs.org/playwright-core/-/playwright-core-{PLAYWRIGHT}.tgz',
                  archive, sha512, base64.b64decode(PW_SHA))
            with tarfile.open(archive) as tar:
                tar.extractall(folder, filter='data')
            (folder/'package').replace(driver)
    if subprocess.check_output([node,'--version'], text=True).strip() != 'v'+NODE:
        raise ValueError('浏览器驱动的 Node 版本不符')
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(work/'browser-cache'), DEBIAN_FRONTEND='noninteractive')
    cli = [node,driver/'cli.js']
    if subprocess.check_output([*cli,'--version'], text=True,env=env).strip() != 'Version '+PLAYWRIGHT:
        raise ValueError('Playwright 版本不符')
    subprocess.run([*cli,'install','--with-deps','--only-shell','chromium'],env=env, timeout=720,check=True)
    print('BROWSER READY', flush=True)


if __name__ == '__main__':
    install(Path(sys.argv[1]).resolve())
