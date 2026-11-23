"""Single-consumer SQLite queue. Only committed chat turns publish jobs."""

import asyncio
from contextlib import closing, suppress
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from app.adapters.esmfold2 import BiohubError, ESMFold2Adapter
from app.adapters.mock import MockAdapter
from app.adapters.openprotein import OpenProteinAdapter, OpenProteinError
from app.adapters.protenix import ProtenixAdapter, ProtenixError
from app.config import PublicError, Settings
from app.schemas import FoldModel, JobView
from app.storage import Store
from app.structures import InvalidOutput, verified_pdb

ERRORS = {
    'execution_error': '执行器出错，未生成可用结构。',
    'timeout': '等待执行结果超时，本地任务已结束。',
    'invalid_output': '结构文件缺失、被修改、与本任务不匹配，或没有可解析的蛋白质坐标。',
    'interrupted': '服务已停止或重启，未完成的任务已终止，没有自动重交。',
    'openprotein_auth': 'OpenProtein 登录或令牌验证失败，请核对后端账号凭证。',
    'openprotein_access': 'OpenProtein 拒绝访问，请检查账号授权与服务可用地区。',
    'openprotein_quota': 'OpenProtein 拒绝了额度请求，请核对免费配额。',
    'openprotein_limit': 'OpenProtein 已限流，请查看平台任务记录。',
    'openprotein_input': 'OpenProtein 拒绝了模型输入或请求参数。',
    'openprotein_missing': 'OpenProtein 未找到请求的模型、任务或结构。',
    'openprotein_execution': 'OpenProtein 报告远程任务失败或已取消。',
    'openprotein_connection': '后端无法连接 OpenProtein。',
    'openprotein_upstream': 'OpenProtein 服务返回了异常响应。',
    'biohub_auth': 'Biohub 拒绝了 API key（401）。请核对后端凭证。',
    'biohub_credits': 'Biohub 拒绝了额度请求（402）。请检查账户的免费 credits。',
    'biohub_access': 'Biohub 拒绝访问（403）。请检查模型权限和平台限制。',
    'biohub_input': 'Biohub 拒绝了本次折叠输入（422）。',
    'biohub_rate_limit': 'Biohub 已限流（429）。可在 Rate Limits 查看账户限制。',
    'biohub_region': 'Biohub 限制了当前网络所在地区的访问（451）。',
    'biohub_upstream': 'Biohub 收到请求后未返回成功响应。',
    'biohub_connection': '后端无法完成与 Biohub 的网络连接。',
    'protenix_cli': '无法启动 Protenix CLI，请检查可执行文件和隔离环境。',
    'protenix_version': 'Protenix CLI 版本不匹配，此配置要求官方包 2.0.0。',
    'protenix_execution': 'Protenix CLI 报告执行失败，请查看本任务的 cli-events.jsonl 和输出错误目录。',
    'protenix_oom': 'Protenix 运行时内存不足。请核对 GPU 剩余显存及主机内存。',
    'protenix_cuda': 'Protenix 无法使用 CUDA，请核对 GPU 与驱动。',
    'protenix_download': 'Protenix 无法下载依赖，请检查官方权重和 CCD 缓存。',
}


def utc():
    return datetime.now(timezone.utc).isoformat()


class Submission:
    """Reservations belong to one chat turn; side effects begin only on commit."""
    def __init__(self, service: 'JobService', cid: UUID):
        self.service, self.store, self.cid = service, service.store, cid
        self.rows: dict[tuple[str, str], dict] = {}

    def submit(self, sequence: str, model: FoldModel) -> dict:
        mode = self.service.config.mode(model)
        adapter = self.service.adapters.get((model, mode))
        if adapter is None:
            code = f'{self.service.config.esmfold2_provider}_config' if model == 'esmfold2' else 'real_unavailable'
            return {'code': code, 'model': model}
        # Different provider IDs or differently formatted representations of the
        # same normalized input must not create a second job within a turn.
        key = (sequence, model)
        if key not in self.rows:
            params = adapter.parameters()
            params['timeout_seconds'] = getattr(adapter, 'timeout_seconds', self.service.config.job_timeout)
            self.rows[key] = dict(id=str(uuid4()), conversation_id=str(self.cid), sequence=sequence, model=model,
                                  model_version=adapter.version, mode=mode, created_at=utc(), parameters=json.dumps(params),
                                  seed=params.get('seed'))
        row = self.rows[key]
        return {'code': 'job_submitted', 'id': row['id'], 'status': 'queued', 'model': model, 'mode': mode,
                'model_version': row['model_version'], 'length': len(sequence),
                'fixture_source': json.loads(row['parameters']).get('source'), 'result_available': False}

    def status(self, cid: UUID, job_id: UUID) -> dict:
        try:
            job = self.service.view(cid, job_id)
        except PublicError as e:
            if e.code == 'job_not_found':
                return {'code': 'job_not_found'}
            raise
        return {'code': 'job_status', **job.model_dump(mode='json', include={
            'id', 'status', 'model', 'mode', 'model_version', 'error', 'error_message', 'result_available', 'fixture_source'})}


class JobService:
    def __init__(self, store: Store, config: Settings, http: httpx.AsyncClient):
        self.store, self.config = store, config
        self.root = store.path.parent / 'jobs'
        self.adapters = {(m, 'mock'): MockAdapter(m, delay=config.mock_delay) for m in ('esmfold2', 'protenix')
                         if config.mode(m) == 'mock'}
        if config.esmfold2_mode == 'real':
            if config.esmfold2_provider == 'openprotein':
                if config.openprotein_username and config.openprotein_password:
                    self.adapters['esmfold2', 'real'] = OpenProteinAdapter(http, config.openprotein_username,
                                                                         config.openprotein_password)
            elif config.esmfold2_provider == 'biohub' and config.biohub_configured:
                self.adapters['esmfold2', 'real'] = ESMFold2Adapter(http, config.esmfold2_key)
        if config.protenix_mode == 'real' and (cli := config.protenix_cli):
            self.adapters['protenix', 'real'] = ProtenixAdapter(cli, config.protenix_root)
        self.wake = asyncio.Event()
        self.worker: asyncio.Task | None = None

    def start(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE jobs SET status='failed',error='interrupted',finished_at=?,output_path=NULL,sha256=NULL "
                       "WHERE status IN ('queued','running')", (utc(),))
        self.worker = asyncio.create_task(self._consume(), name='protein-job-worker')

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            with suppress(asyncio.CancelledError):
                await self.worker

    def transaction(self, cid: UUID) -> Submission:
        return Submission(self, cid)

    def _claim(self):
        with closing(self.store.connect()) as db, db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running',started_at=? WHERE id=? AND status='queued'", (utc(), row['id']))
                return dict(row)

    async def _consume(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            while row := self._claim():
                await self._run(row)

    def _log(self, directory: Path, status: str, error: str | None = None):
        try:
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
                print(json.dumps(dict(utc=utc(), status=status, error=error)), file=stream)
        except OSError:
            logging.getLogger(__name__).warning('Unable to write job event: %s', directory.name)

    async def _run(self, row):
        directory = self.root / row['id']
        error = None
        try:
            directory.mkdir(mode=0o700)
            params = json.loads(row['parameters'])
            record = {k: row[k] for k in ('id','conversation_id','sequence','model','model_version','mode','seed','created_at')}
            (directory / 'input.json').write_text(json.dumps({**record, 'parameters': params}, indent=2), encoding='utf-8')
            self._log(directory, 'running')
            async with asyncio.timeout(params['timeout_seconds']):
                adapter = self.adapters[row['model'], row['mode']]
                path = await adapter.predict(row['sequence'], directory, params)
                _, digest = verified_pdb(directory, path, mock=row['mode'] == 'mock', sequence=row['sequence'])
            with closing(self.store.connect()) as db, db:
                db.execute("UPDATE jobs SET status='succeeded',finished_at=?,output_path=?,sha256=? WHERE id=? AND status='running'",
                           (utc(), path.relative_to(self.root).as_posix(), digest, row['id']))
        except asyncio.CancelledError:
            error = 'interrupted'
            raise
        except TimeoutError:
            error = 'timeout'
        except InvalidOutput:
            error = 'invalid_output'
        except (BiohubError, OpenProteinError, ProtenixError) as exc:
            error = str(exc)
        except Exception:
            # Don't echo exceptions: adapter output and filesystem paths may be private.
            error = 'execution_error'
        finally:
            if error:
                self._fail(row['id'], error)
            self._log(directory, 'failed' if error else 'succeeded', error)

    def _fail(self, jid: str, error: str):
        with closing(self.store.connect()) as db, db:
            db.execute("UPDATE jobs SET status='failed',finished_at=?,error=?,output_path=NULL,sha256=NULL WHERE id=?",
                       (utc(), error, jid))

    def _lookup(self, cid: UUID, jid: UUID):
        row = self.store.job(cid, jid)
        if row is None:
            raise PublicError(404, 'job_not_found', '本会话不存在这个任务。')
        return row

    def _read(self, row):
        directory = self.root / row['id']
        try:
            if not row['sha256'] or row['output_path'] != f"{row['id']}/structure.pdb":
                raise InvalidOutput()
            return verified_pdb(directory, directory / 'structure.pdb', mock=row['mode'] == 'mock',
                                digest=row['sha256'], sequence=row['sequence'])[0]
        except (InvalidOutput, OSError):
            self._fail(row['id'], 'invalid_output')
            if directory.is_dir() and not directory.is_symlink() and not self.root.is_symlink():
                self._log(directory, 'failed', 'invalid_output')
            raise PublicError(409, 'invalid_output', ERRORS['invalid_output']) from None

    @staticmethod
    def _name(row):
        return f"{row['model']}-{row['mode']}-{row['id']}.pdb"

    def view(self, cid: UUID, jid: UUID) -> JobView:
        row = self._lookup(cid, jid)
        if row['status'] == 'succeeded':
            try:
                self._read(row)
            except PublicError:
                row = self._lookup(cid, jid)
        params = json.loads(row['parameters'])
        ready = row['status'] == 'succeeded'
        return JobView(**{k: row[k] for k in ('id','conversation_id','model','model_version','mode','status','created_at',
                                               'started_at','finished_at','seed','error','sha256')},
                       length=len(row['sequence']), parameters=params, error_message=ERRORS.get(row['error']),
                       fixture_source=params.get('source') if row['mode']=='mock' else None,
                       result_available=ready, download_name=self._name(row) if ready else None)

    def structure(self, cid: UUID, jid: UUID):
        row = self._lookup(cid, jid)
        if row['status'] != 'succeeded':
            raise PublicError(409, 'structure_unavailable', '任务没有可用的结构文件。')
        return self._read(row), self._name(row)
