"""Embed only the deployed app, hashed frontend build, GPU pins and acceptance tools."""

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from build_protenix_colab import cell

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT/'colab/protenix_chat_round6.ipynb'
FIFTH = ROOT/'colab/protenix_mini_ubiquitin.ipynb'
APP = ('__init__', 'agent', 'config', 'jobs', 'llm_client', 'main', 'schemas', 'sequences', 'storage', 'structures',
       'tools', 'adapters/__init__', 'adapters/protenix', 'adapters/esmfold2', 'adapters/openprotein', 'adapters/mock')
SUPPORT = ('backend/requirements.lock', 'colab/resources.py', 'colab/ubiquitin.py', 'colab/requirements-linux-py311.lock',
           'colab/round6.py', 'colab/round6_evidence.py', 'colab/round6_browser_install.py',
           'frontend/tests/browser-check.mjs', 'frontend/dist/index.html')


def runtime_files():
    assets = ROOT/'frontend/dist/assets'
    matched = sorted(p.relative_to(ROOT).as_posix() for p in assets.iterdir()
                     if re.fullmatch(r'(index-[\w-]+\.(js|css)|StructureViewer-[\w-]+\.js)',p.name))
    if len(matched) != 3:
        raise ValueError('先运行前端生产构建，检查入口 JS、CSS、Mol* 块')
    return sorted([*SUPPORT, *('backend/app/'+n+'.py' for n in APP), *matched])


def notebook():
    buf = BytesIO()
    with ZipFile(buf,'w') as z:
        for name in runtime_files():
            z.writestr(ZipInfo(name), (ROOT/name).read_bytes(), ZIP_DEFLATED)
    encoded = base64.encodebytes(buf.getvalue()).decode().rstrip()
    digest = sha256(buf.getvalue()).hexdigest()
    old = json.loads(FIFTH.read_bytes())
    prep = [c for c in old['cells'] if c['id'] in ('gpu','install','assets')]
    cells = [cell('markdown','intro',"""
        # 用一次真实聊天预测 76 aa 泛素

        在免费 Colab 选择「运行时 → 更改运行时类型 → T4 GPU」。免费 GPU 不可用时暂停。左栏钥匙图标 **Secrets** 中添加名称 **DEEPSEEK_API_KEY**，值填本人已有的 DeepSeek API key，并为本笔记本开启 **Notebook access**。只在 Secrets 中输入值。

        依次运行 1–7。完整泛素、后端、构建好的前端和运行包已内置。1–3 沿用第五轮已实测的 T4 环境。4–5 准备 FastAPI 和浏览器。第 6 单元通过本虚拟机的聊天 API 发送一条消息，DeepSeek 使用已有对话额度。一个后端进程处理聊天、调用官方 CLI，并向同一台虚拟机上的 Chromium 提供 Mol* 所需的结构。第 7 单元把证据下载到电脑。
        """), *prep,
        cell('code','app',"""
        # @title 4 · 校验内置运行包，安装独立 FastAPI 环境
        if not assets_ok:
            raise RuntimeError('请先完成第 1–3 单元')
        work = Path('/content/protenix-round6')
        project = work/'project'
        work.mkdir(exist_ok=True)
        binary = base64.b64decode('''PAYLOAD''')
        if hashlib.sha256(binary).hexdigest() != 'DIGEST':
            raise RuntimeError('内置运行包摘要不符')
        with zipfile.ZipFile(io.BytesIO(binary)) as z:
            z.extractall(project)
        del binary
        app_py = work/'backend-venv/bin/python'
        if not app_py.is_file():
            call([*tool, 'venv', '--managed-python','--python','3.11.13',app_py.parents[1]])
        call([*tool,'pip','install','--python',app_py,'--no-deps','--default-index','https://pypi.org/simple',
              '-r',project/'backend/requirements.lock'])
        call([*tool,'pip','check','--python',app_py])
        driver = project/'colab/round6.py'
        call([app_py,driver,'--help'])
        print('BACKEND READY · 单进程 · 仅使用 127.0.0.1')
        """),
        cell('code','viewer-setup',"""
        # @title 5 · 准备本机 Chromium，供第 6 单元操作 Mol*
        ready = work/'browser-ready.json'
        ready.unlink(missing_ok=True)
        try:
            call([app_py,project/'colab/round6_browser_install.py',work], timeout=900)
            ready.write_text(json.dumps({'playwright':'1.62.1'}))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            print('BROWSER PARTIAL · 可继续第 6、7 单元。成功任务也可在 Mac 验证画布和下载。')
        """),
        cell('code','chat',"""
        # @title 6 · 发送一次聊天，在同一后端完成推理、Mol* 和下载验收
        # The key lives only in this function and is sent to the backend on stdin.
        def run_chat():
            from google.colab import userdata
            from contextlib import closing, suppress
            import signal, sqlite3, threading
            db = work/'data/app.sqlite3'
            committed = False
            if db.is_file():
                with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
                    committed = conn.execute('SELECT 1 FROM turns LIMIT 1').fetchone() is not None
            key = ''
            if not committed:
                try:
                    key = userdata.get('DEEPSEEK_API_KEY')
                except Exception:
                    raise RuntimeError('请在左栏 Secrets 添加 DEEPSEEK_API_KEY 并开启本笔记本的访问权限') from None
                if not isinstance(key,str) or not key.strip() or any(c in key for c in ('\\n','\\r')):
                    raise RuntimeError('Secrets 中的 DeepSeek 凭证为空或带有换行')
            stage = 'view' if committed else 'run'
            with subprocess.Popen([str(app_py),str(driver),stage,str(work),str(root)], env=env, cwd=project,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, errors='replace', start_new_session=True) as proc:
                proc.stdin.write(key.strip()+'\\n')
                proc.stdin.close()
                del key
                def output():
                    for line in proc.stdout:
                        print(line,end='',flush=True)
                reader = threading.Thread(target=output,daemon=True)
                reader.start()
                try:
                    code = proc.wait(timeout=2220)
                except (KeyboardInterrupt,subprocess.TimeoutExpired):
                    with suppress(ProcessLookupError):
                        os.killpg(proc.pid,signal.SIGINT)
                    try:
                        proc.wait(timeout=12)
                    except subprocess.TimeoutExpired:
                        with suppress(ProcessLookupError):
                            os.killpg(proc.pid,signal.SIGKILL)
                    raise
                finally:
                    reader.join(timeout=5)
                if code:
                    raise RuntimeError('请查看上方的阶段或错误代码。可先运行第 7 单元保留已取得的证据。')
        run_chat()
        """),
        cell('code','download',"""
        # @title 7 · 下载本次聊天的证据 ZIP（也可下载部分结果）
        from google.colab import files
        latest = work/'latest.json'
        if not latest.is_file():
            raise RuntimeError('尚无第六轮证据 ZIP，请反馈失败的单元和最后一条错误')
        result = work/json.loads(latest.read_bytes())['file']
        print('请放回项目 examples/outputs/：', result.name)
        files.download(str(result))
        call([app_py,driver,'verify',result])
        """),
        cell('markdown','finish',"""
        完整成功会打印 **CHAT + GPU OK**、**STRUCTURE HTTP OK**、**MOLSTAR + DOWNLOAD OK** 和同一个任务 UUID。把第 7 单元的 **round6-protenix-….zip** 放回项目的 **examples/outputs/**。浏览器安装、画布或下载出错时，直接运行第 7 单元，保留该任务。也可在当前会话重跑第 5–7 单元，第 6 单元将只读复核已提交的任务。若 Colab 下载弹窗没有出现，左侧文件栏中可下载 /content/protenix-round6/ 下同名 ZIP。

        反馈单元编号、最后一条脱敏错误和任务 UUID（若已生成）即可。GPU 故障可附 GPU 名和剩余显存 MiB。运行时回收后，已下载的成功任务可在 Mac 继续检查。[免费 Colab 资源说明](https://research.google.com/colaboratory/faq.html) · [Colab Secrets](https://github.com/googlecolab/colabtools/blob/main/google/colab/userdata.py)
        """)]
    c = next(c for c in cells if c['id']=='app')
    c['source'] = ''.join(c['source']).replace('PAYLOAD',encoded).replace('DIGEST',digest).splitlines(keepends=True)
    return {**old, 'cells':cells}


if __name__ == '__main__':
    NOTEBOOK.write_text(json.dumps(notebook(), ensure_ascii=False, indent=1)+'\n', encoding='utf-8')
