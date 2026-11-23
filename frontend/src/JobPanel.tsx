import { lazy, Suspense, useEffect, useState } from 'react'
import { getJob, jobPath, type Job } from './api'

const Viewer = lazy(() => import('./StructureViewer'))
const statusText = { queued: '排队中', running: '运行中', succeeded: '已完成', failed: '失败' }
const modelName = { esmfold2: 'ESMFold2', protenix: 'Protenix' }
const time = (s: string) => new Date(s).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'})

export default function JobPanel({cid, ids}: {cid:string; ids:string[]}) {
  const [selected, select] = useState<string>()
  return <section className="jobs-panel" aria-label="本会话的任务">
    <div className="jobs-heading"><div><p className="eyebrow">STRUCTURE JOBS</p><h2>结构任务 <small>{ids.length}</small></h2></div>
      <p>后台逐个处理；等待期间可以继续对话。</p></div>
    {[...ids].reverse().map(id => <JobCard key={id} id={id} cid={cid} open={id === selected}
      toggle={() => select(current => current === id ? undefined : id)} />)}
  </section>
}

function JobCard({cid, id, open, toggle}: {cid:string; id:string; open:boolean; toggle:()=>void}) {
  const [job, setJob] = useState<Job>()
  const [problem, setProblem] = useState('')
  const [revision, refresh] = useState(0)
  const [downloadError, setDownloadError] = useState('')
  useEffect(() => {
    let active = true, timer: number | undefined
    async function poll() {
      let again = true
      try {
        const current = await getJob(cid, id)
        if (!active) return
        setJob(current); setProblem('')
        again = current.status === 'queued' || current.status === 'running'
      } catch (e) {
        if (active) setProblem(e instanceof Error ? e.message : '暂时无法读取任务。')
      }
      if (active && again) timer = window.setTimeout(poll, 2000)
    }
    void poll()
    return () => {active = false; window.clearTimeout(timer)}
  }, [cid, id, revision])

  async function download() {
    setDownloadError('')
    try {
      const response = await fetch(jobPath(cid, id, true, true), {cache:'no-store', signal:AbortSignal.timeout(10000)})
      if (!response.ok || !response.headers.get('content-type')?.includes('chemical/x-pdb') || !job?.download_name) throw new Error()
      const url = URL.createObjectURL(await response.blob())
      const a = document.createElement('a'); a.href = url; a.download = job.download_name; a.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {setDownloadError('文件无法下载，已重新查询任务。'); refresh(n => n + 1)}
  }
  async function returnResult(file: File) {
    setDownloadError('')
    try {
      const response = await fetch(`/api/jobs/${id}/colab-result?conversation_id=${cid}`, {
        method: 'POST', headers: {'Content-Type':'application/json'}, body: file,
      })
      if (!response.ok) throw new Error((await response.json()).error?.message || '结果文件未被接收。')
      if (!open) toggle()
      refresh(n => n + 1)
    } catch (error) { setDownloadError(error instanceof Error ? error.message : '请重新选择文件。') }
  }
  const good = job?.status === 'succeeded' && job.result_available && !problem
  return <article className="job-card" data-job-id={id} aria-label={`任务 ${id}`}>
    <div className="job-title"><h3>{job ? modelName[job.model] : '读取任务…'}</h3>
      {job && <span className={'mode-tag '+job.mode}>{job.mode === 'mock' ? 'Mock · 示例' : 'Real'}</span>}
      <span role="status" className={'job-state '+(problem ? '' : job?.status)}>{problem ? '状态待确认' : job ? statusText[job.status] : '读取中'}</span>
    </div>
    <code className="job-id">{id}</code>
    {job && <><p className="job-meta">输入 {job.length} aa · {job.model_version} · 提交 {time(job.created_at)}{job.finished_at && ' · 结束 '+time(job.finished_at)}</p>
      {job.mode === 'mock' && <p className="fixture-note"><strong>示例结构，非输入序列的真实预测。</strong> 来源：<a href="https://www.rcsb.org/structure/1UBQ" target="_blank" rel="noreferrer">RCSB PDB · 1UBQ</a>（泛素，X 射线晶体结构）。</p>}
      {job.parameters?.execution === 'colab_notebook' && job.status === 'running' && <div className="colab-transfer">
        <p>等待 Colab 结果。下载本任务的笔记本，在免费 T4 中运行全部单元，再选择它生成的 JSON。请在一小时内完成，并保持后端运行。</p>
        <p><a href={`/api/jobs/${id}/colab-notebook?conversation_id=${cid}`} download>下载本任务笔记本</a> · <a href="https://colab.research.google.com/" target="_blank" rel="noreferrer">打开 Colab</a></p>
        <label>交回本任务的结果 JSON <input type="file" accept=".json" onChange={e => {
          const file = e.currentTarget.files?.[0]; e.currentTarget.value = ''; if (file) void returnResult(file)
        }}/></label>
      </div>}
      {job.status === 'failed' && <p className="job-error" role="alert">{job.error_message || '任务失败，没有可用的结构。'} <code>{job.error}</code></p>}</>}
    {problem && <p className="job-error" role="alert">{problem} 将重试连接，任务状态以服务端为准。</p>}
    {downloadError && <p className="job-error" role="alert">{downloadError}</p>}
    {good && job && <><div className="job-actions"><button onClick={toggle} aria-expanded={open}>{open ? '关闭三维结构' : '查看三维结构'}</button>
      <button onClick={() => void download()}>下载 {job.mode === 'mock' ? 'Mock' : 'Real'} PDB</button></div>
      {open && <Suspense fallback={<p role="status">正在加载 Mol*…</p>}><Viewer job={job} onFileError={() => refresh(n => n + 1)} /></Suspense>}</>}
  </article>
}
