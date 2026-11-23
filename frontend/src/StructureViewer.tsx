import { useEffect, useRef, useState } from 'react'
import { PluginContext } from 'molstar/lib/mol-plugin/context'
import { DefaultPluginSpec } from 'molstar/lib/mol-plugin/spec'
import { PluginConfig } from 'molstar/lib/mol-plugin/config'
import { Color } from 'molstar/lib/mol-util/color'
import { jobPath, type Job } from './api'

export default function StructureViewer({job, onFileError}: {job:Job; onFileError:()=>void}) {
  const host = useRef<HTMLDivElement>(null)
  const plugin = useRef<PluginContext | undefined>(undefined)
  const onError = useRef(onFileError)
  onError.current = onFileError
  const [state, setState] = useState('正在载入三维结构…')
  const [attempt, retry] = useState(0)

  useEffect(() => {
    let live = true, observer: ResizeObserver | undefined
    const cancel = new AbortController()
    const slot = document.createElement('div')
    slot.className = 'mol-slot'
    host.current!.appendChild(slot)
    const ctx = new PluginContext({...DefaultPluginSpec(), config:[
      [PluginConfig.VolumeStreaming.Enabled, false], [PluginConfig.General.AllowMajorPerformanceCaveat, true],
    ]})
    let released = false, initialized = false
    function release() {
      if (!released && initialized) {released = true; ctx.dispose()}
    }
    async function setup() {
      let fetchingFile = false
      try {
        setState('正在载入三维结构…')
        await ctx.init(); initialized = true
        if (!live) return
        if (!await ctx.mountAsync(slot)) throw new Error('WebGL 无法启动；请检查浏览器的硬件加速设置。')
        if (!live) return
        ctx.canvas3d?.setProps({renderer:{backgroundColor:Color(0xf2f5ef)}})
        fetchingFile = true
        const response = await fetch(jobPath(job.conversation_id, job.id, true), {
          cache:'no-store',signal:AbortSignal.any([cancel.signal, AbortSignal.timeout(10000)])})
        if (!response.ok) throw new Error('该任务的结构文件无法读取。')
        const pdb = await response.text()
        fetchingFile = false
        if (!live) return
        const data = await ctx.builders.data.rawData({data:pdb, label:job.download_name || job.id})
        const b = ctx.builders.structure
        const trajectory = await b.parseTrajectory(data, 'pdb')
        const model = await b.createModel(trajectory)
        const structure = await b.createStructure(model)
        const polymer = await b.tryCreateComponentStatic(structure, 'polymer')
        if (!polymer) throw new Error('文件中没有可显示的蛋白质。')
        const rep = await b.representation.addRepresentation(polymer, {type:'cartoon',color:'secondary-structure'})
        if (!rep.obj) throw new Error('Mol* 未生成结构表示。')
        if (!live) return
        plugin.current = ctx
        observer = new ResizeObserver(() => ctx.handleResize()); observer.observe(slot)
        ctx.canvas3d?.requestCameraReset({durationMs:0})
        setState('')
      } catch (e) {
        if (live) {
          setState(e instanceof Error ? '无法显示：'+e.message : 'Mol* 无法显示该文件。')
          if (fetchingFile) onError.current()
        }
      } finally { if (!live) release() }
    }
    void setup()
    return () => {live = false; cancel.abort(); observer?.disconnect(); plugin.current = undefined; slot.remove(); release()}
  }, [job.conversation_id, job.id, job.download_name, attempt])
  return <figure className="viewer"><figcaption><strong>Mol* · {job.mode === 'mock' ? '1UBQ 示例结构' : 'Real 预测结构'}</strong>
    <span>拖动旋转 · 滚轮或双指缩放</span></figcaption>
    <div className="mol-host" ref={host} aria-label={`三维结构 ${job.id}`}/>
    {state ? <p role="status">{state} {state.startsWith('无法') && <button onClick={() => retry(x => x+1)}>重试显示</button>}</p> :
      <button className="reset-camera" onClick={() => plugin.current?.canvas3d?.requestCameraReset({durationMs:150})}>复位视角</button>}
  </figure>
}
