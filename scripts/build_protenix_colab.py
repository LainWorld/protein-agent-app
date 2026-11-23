"""Build the single uploadable notebook from an explicit, credential-free list of project files."""

import base64
import hashlib
import io
import json
from pathlib import Path
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'colab/protenix_mini_ubiquitin.ipynb'
SUPPORT = ('backend/app/adapters/protenix.py', 'backend/app/structures.py', 'colab/resources.py',
           'colab/ubiquitin.py', 'colab/requirements-linux-py311.lock')


def cell(kind, label, source):
    result = dict(id=label, cell_type=kind, metadata={}, source=textwrap.dedent(source).strip().splitlines(keepends=True))
    if kind == 'code':
        result.update(execution_count=None, outputs=[], metadata={'cellView': 'form'})
    return result


def notebook():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        for name in SUPPORT:
            # Fixed ZIP timestamps make independent builds byte-identical.
            archive.writestr(zipfile.ZipInfo(name), (ROOT / name).read_bytes(), zipfile.ZIP_DEFLATED)
    binary = payload.getvalue()
    embedded = '\n'.join(textwrap.wrap(base64.b64encode(binary).decode(), width=100))
    cells = [
        cell('markdown', 'intro', """
        # 用免费 T4 预测 76 aa 泛素

        在免费 Colab 中选择 **代码执行程序 → 更改运行时类型 → T4 GPU → 保存**。部分界面使用「运行时」或 Runtime。若仅能购买计算单元或升级，请停在选择页面。按顺序运行以下五个单元。安装文件、完整序列和校验程序都在这份笔记本里。

        本次使用官方 Protenix 2.0.0、Mini default v0.5.0、种子 101。第 4 单元发起一次独立推理，第 5 单元将原始 mmCIF、PDB 和运行证据打包到你的电脑。全程使用临时磁盘，无需挂载 Drive、提供密钥或上传其他文件。
        """),
        cell('code', 'gpu', """
        # @title 1 · 检查免费 T4、CUDA、显存和磁盘
        import base64, hashlib, io, json, os, platform, re, shutil, subprocess, sys, uuid, zipfile
        from pathlib import Path

        gpu_ok = install_ok = assets_ok = prediction_ok = False
        run_id = None
        root = Path('/content/protenix-round5')
        if platform.system() != 'Linux' or platform.machine() != 'x86_64' or not shutil.which('nvidia-smi'):
            raise RuntimeError('未检测到 Colab NVIDIA GPU。请检查运行时类型和免费配额。')
        query = 'name,driver_version,memory.total,memory.free,compute_cap'
        smi = subprocess.check_output(['nvidia-smi', '--query-gpu=' + query, '--format=csv,noheader,nounits'], text=True)
        name, driver, total, free, cc = [s.strip() for s in smi.splitlines()[0].split(',')]
        banner = subprocess.check_output(['nvidia-smi'], text=True)
        cuda = re.search(r'CUDA Version:\\s*([0-9.]+)', banner)
        disk = shutil.disk_usage('/content').free / 2**30
        nvcc = subprocess.check_output(['nvcc', '--version'], text=True).splitlines()[-1] if shutil.which('nvcc') else '未安装'
        hardware = dict(gpu=name, driver=driver, driver_cuda=cuda[1] if cuda else 'unknown', toolkit=nvcc,
                        capability=cc, total_vram_mib=int(total), free_vram_mib=int(free), free_disk_gib=round(disk, 2))
        print(json.dumps(hardware, ensure_ascii=False, indent=2))
        if 'T4' not in name or cc != '7.5':
            raise RuntimeError('本次验收使用免费 T4。请检查分配的显卡。')
        root.mkdir(parents=True, exist_ok=True)
        (root / 'hardware.json').write_text(json.dumps(hardware, indent=2))
        gpu_ok = True
        print('GPU OK ·', name)
        """),
        cell('markdown', 'setup-note', """
        安装到会话内的独立 Python 3.11.13 环境。依赖含 CUDA 库，首次下载可能较慢。完成时会打印 **CLI OK**、实际 GPU 和 CUDA 版本。可从 Colab 的文件栏查看解包后的源码和依赖清单。
        """),
        cell('code', 'install', """
        # @title 2 · 安装锁定环境，实测 CUDA 运算并检查官方 CLI
        if not gpu_ok:
            raise RuntimeError('请先完成第 1 单元')
        install_ok = assets_ok = prediction_ok = False
        support = root / 'support'
        payload = base64.b64decode('''__PAYLOAD__''')
        if hashlib.sha256(payload).hexdigest() != '__DIGEST__':
            raise RuntimeError('笔记本内置文件校验失败')
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            archive.extractall(support)
        env = {k: os.environ[k] for k in ('HOME','PATH','LANG','TMPDIR','LD_LIBRARY_PATH','CUDA_HOME','CUDA_VISIBLE_DEVICES')
               if k in os.environ}
        env.update(UV_PYTHON_INSTALL_DIR=str(root/'interpreters'), UV_CACHE_DIR=str(root/'uv-cache'),
                   DS_BUILD_OPS='0', LAYERNORM_TYPE='torch', PROTENIX_ROOT_DIR=str(root/'cache'), PYTHONNOUSERSITE='1')

        def call(args, timeout=1800):
            # Relay subprocess output to the notebook cell even when the kernel redirects its own stdout.
            import signal, threading
            from contextlib import suppress
            command = [str(s) for s in args]
            with subprocess.Popen(command, env=env, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors='replace', start_new_session=True) as process:
                def show_output():
                    for line in process.stdout:
                        print(line, end='', flush=True)
                reader = threading.Thread(target=show_output, daemon=True)
                reader.start()
                try:
                    code = process.wait(timeout=timeout)
                except (KeyboardInterrupt, subprocess.TimeoutExpired):
                    # SIGINT lets the Python inference driver cancel its own CLI process group.
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGINT)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(process.pid, signal.SIGKILL)
                    raise
                finally:
                    reader.join(timeout=5)
                if code:
                    raise subprocess.CalledProcessError(code, command)

        bootstrap = root / 'bootstrap'
        uv = bootstrap / 'bin/uv'
        call([sys.executable, '-m', 'pip', '--isolated', 'install', '--no-deps', '--disable-pip-version-check',
              '--target', bootstrap, '--upgrade', '--index-url', 'https://pypi.org/simple', 'uv==0.9.18'])
        tool = [uv, '--no-config']
        call([*tool, 'python', 'install', '3.11.13'])
        py = root / 'venv/bin/python'
        if not py.is_file():
            call([*tool, 'venv', '--managed-python', '--python', '3.11.13', py.parents[1]])
        pins = (support/'colab/requirements-linux-py311.lock').read_text().splitlines()
        base = root / 'base.lock'
        base.write_text('\\n'.join(p for p in pins if not p.startswith(('deepspeed==', 'protenix=='))) + '\\n')
        install = [*tool, 'pip', 'install', '--python', py, '--no-deps', '--default-index', 'https://pypi.org/simple']
        call([*install, '-r', base])
        # DeepSpeed's source build can inspect torch and setuptools. Both were installed above.
        wheel = ('https://files.pythonhosted.org/packages/a1/df/0f23f78428d4a5baaa6239ac1504994ee068b39a9facaff97f50cff547b7/'
                 'protenix-2.0.0-py3-none-any.whl#sha256=be4584dda688e0518ce12909d8d51d0a0868e7daa2bbb95cbac17440c0ac309f')
        call([*install, '--no-build-isolation-package', 'deepspeed', 'deepspeed==0.17.5', wheel])
        call([*tool, 'pip', 'check', '--python', py])
        runner = support / 'colab/ubiquitin.py'
        call([py, runner, 'check-install', root])
        install_ok = True
        """),
        cell('code', 'assets', """
        # @title 3 · 下载并逐个校验 Mini 权重及四份公共缓存
        if not install_ok:
            raise RuntimeError('请先完成第 2 单元')
        assets_ok = prediction_ok = False
        call([py, support/'colab/resources.py', root/'cache'], timeout=3600)
        assets_ok = True
        """),
        cell('markdown', 'predict-note', """
        第 3 单元打印 **ASSETS OK · 5/5** 后再运行预测。固定输入为项目的完整 76 aa 泛素，关闭 MSA 和模板，使用 FP32、Torch 内核、4 个循环、5 个扩散步和 1 个样本。结果保存在此次运行编号对应的目录中。
        """),
        cell('code', 'predict', """
        # @title 4 · 用官方 CLI 运行一次泛素推理
        if not assets_ok:
            raise RuntimeError('请先完成第 3 单元')
        if not prediction_ok:
            # Recheck after large downloads, in a short-lived copy of the exact CLI interpreter.
            call([py, '-c', "import torch; assert torch.cuda.is_available() and torch.cuda.get_device_capability() == (7, 5), 'T4 CUDA unavailable'"])
            run_id = str(uuid.uuid4())
            print('运行编号', run_id, flush=True)
            call([py, runner, 'predict', root, run_id], timeout=1860)
            prediction_ok = True
        else:
            print('本次推理已完成，请运行第 5 单元', run_id)
        """),
        cell('code', 'export', """
        # @title 5 · 解析结构，导出并下载证据 ZIP
        if not prediction_ok:
            raise RuntimeError('请先取得第 4 单元的 PREDICTION OK')
        call([py, runner, 'export', root, run_id])
        from google.colab import files
        result = root / f'protenix-mini-ubiquitin-{run_id}.zip'
        print('下载后原样放回项目的 examples/outputs/。若浏览器未弹出下载，可从左侧文件栏下载', result)
        files.download(str(result))
        """),
        cell('markdown', 'finish', """
        **成功标志**为 `VERIFIED · 1 chain · 76 aa`、原子数和 ZIP 文件名。第 5 单元可重复下载。若失败，只需反馈单元编号、GPU 名称和最后一条错误（资源下载带文件名和 HTTP/CRC 提示，显存问题带剩余 MiB）。免费 GPU 未分配时可待配额恢复。

        [官方发行包](https://pypi.org/project/protenix/2.0.0/) · [官方 CLI 与模型参数](https://github.com/bytedance/Protenix/blob/v2.0.0/docs/training_inference_instructions.md) · [Colab 免费资源说明](https://research.google.com/colaboratory/faq.html)
        """),
    ]
    source = ''.join(cells[3]['source'])
    cells[3]['source'] = source.replace('__PAYLOAD__', embedded).replace('__DIGEST__', hashlib.sha256(binary).hexdigest()).splitlines(keepends=True)
    return dict(nbformat=4, nbformat_minor=5, cells=cells,
                metadata=dict(accelerator='GPU', colab={'gpuType': 'T4', 'provenance': []},
                              kernelspec={'display_name': 'Python 3', 'name': 'python3'}, language_info={'name': 'python'}))


if __name__ == '__main__':
    NOTEBOOK.write_text(json.dumps(notebook(), ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
