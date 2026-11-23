"""Interactive, task-bound notebook handoff. Never opens a remote connection."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path

from app.adapters.protenix import (MODEL, OPTIONS, PACKAGE, SEED, ProtenixError, cif_path,
                                    cli_args, cli_input, export_pdb)
from app.structures import InvalidOutput

ROOT = Path(__file__).resolve().parents[3]
MAX_RESULT_BYTES = 10_000_000
FAILURES = {'timeout', 'invalid_output', 'protenix_cli', 'protenix_version', 'protenix_execution',
            'protenix_oom', 'protenix_cuda', 'protenix_download'}


def notebook(job_id, sequence):
    nb = json.loads((ROOT/'colab/protenix_mini_ubiquitin.ipynb').read_bytes())
    cells = {c['id']: c for c in nb['cells']}
    intro = cells['intro']
    intro['source'] = [f'# Mac 聊天任务 · Protenix Mini · {len(sequence)} aa\n',
                       f'任务 `{job_id}`。选择免费 T4，依次执行以下四个代码单元。最后把下载的 JSON 交回 Mac 原任务卡。\n',
                       f'输入序列：`{sequence}`']
    predict = cells['predict']
    driver = (ROOT/'colab/chat_result.py').read_text()
    code = f"""# @title 4 · 运行本次聊天任务并下载结果
if not assets_ok:
    raise RuntimeError('请先完成前 3 个单元')
from google.colab import files
job_id = {job_id!r}
sequence = {sequence!r}
result = root/'mac-chat'/job_id/f'protenix-result-{{job_id}}.json'
if not result.exists():
    task_script = root/'mac-chat-task.py'
    task_script.write_text({driver!r})
    env['PYTHONPATH'] = str(support/'backend')
    call([py, task_script, root, job_id, sequence], timeout=1860)
print(json.loads(result.read_text())['status'], result.name)
files.download(str(result))
"""
    predict['source'] = code.splitlines(keepends=True)
    nb['cells'] = [intro, cells['gpu'], cells['install'], cells['assets'], predict]
    return json.dumps(nb, ensure_ascii=False).encode()


class ColabHandoff:
    version = MODEL
    timeout_seconds = 3600  # Includes interactive installation and the return transfer.

    def __init__(self):
        self.waiting = {}

    def parameters(self):
        return dict(execution='colab_notebook', package_version=PACKAGE, seed=SEED, layernorm_type='torch', **OPTIONS)

    async def predict(self, sequence, directory, parameters):
        (directory/'protenix-input.json').write_text(json.dumps(cli_input(directory.name, sequence)))
        result = asyncio.get_running_loop().create_future()
        self.waiting[directory.name] = result
        try:
            receipt = await result
            (directory/'colab-result.json').write_text(json.dumps(receipt))
            if receipt['status'] == 'failed':
                raise ProtenixError(receipt['error'])
            path = cif_path(directory, SEED)
            path.parent.mkdir(parents=True, exist_ok=False)
            path.write_bytes(receipt['cif'].encode())
            (directory/'cli-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in receipt['events']))
            return export_pdb(directory, sequence, SEED)
        finally:
            self.waiting.pop(directory.name, None)

    @staticmethod
    def validate(receipt, jid, sequence):
        if not isinstance(receipt, dict) or (receipt.get('job_id'), receipt.get('sequence'),
                receipt.get('model'), receipt.get('seed')) != (jid, sequence, MODEL, SEED):
            raise ValueError('wrong task')
        if receipt.get('status') == 'failed' and receipt.get('error') in FAILURES:
            return
        events = receipt['events']
        if (receipt.get('status') != 'succeeded' or not isinstance(receipt['cif'], str)
                or sha256(receipt['cif'].encode()).hexdigest() != receipt['sha256']
                or [e['stage'] for e in events] != ['version_started', 'version_exited', 'cli_version',
                                                     'command', 'prediction_started', 'prediction_exited']
                or events[1]['exit_code'] != 0 or events[2]['package_version'] != PACKAGE
                or events[3]['argv'] != ['protenix', *cli_args(dict(seed=SEED, **OPTIONS))]
                or events[-1]['exit_code'] != 0 or events[-1].get('diagnostic') is not None
                or events[-1].get('cuda_selected') is not True):
            raise InvalidOutput('invalid receipt')
