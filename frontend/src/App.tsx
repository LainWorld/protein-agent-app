import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { loadConversation, sendMessage, type Message } from './api'
import JobPanel from './JobPanel'

const storageKey = 'protein-chat.conversation.v2'
const faultDemo = import.meta.env.MODE === 'faults'
const ubiquitin = 'MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG'
function savedId() {
  const linked = new URL(location.href).searchParams.get('conversation')
  if (linked) return linked
  try { return localStorage.getItem(storageKey) || undefined } catch { return undefined }
}
function remember(id?: string) {
  const url = new URL(location.href)
  if (id) url.searchParams.set('conversation', id)
  else url.searchParams.delete('conversation')
  window.history.replaceState(null, '', url)
  try { if (id) localStorage.setItem(storageKey, id); else localStorage.removeItem(storageKey) } catch { /* storage is optional */ }
}
type Attempt = { text: string; id: string }

export default function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [jobs, setJobs] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [failure, setFailure] = useState('')
  const [attempt, setAttempt] = useState<Attempt | null>(null)
  const [conversationId, setConversationId] = useState<string | undefined>(savedId)
  const [restoreId, setRestoreId] = useState(conversationId)
  const [restoreTry, setRestoreTry] = useState(0)
  const [hasConnected, setHasConnected] = useState(false)
  const inFlight = useRef(false)
  const endOfMessages = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    endOfMessages.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, pending, failure])

  useEffect(() => {
    if (!restoreId) return
    let current = true
    setFailure('')
    loadConversation(restoreId).then(history => {
      if (!current) return
      remember(history.conversation_id)
      setMessages(history.messages); setJobs(history.job_ids); setHasConnected(true); setRestoreId(undefined)
    }).catch(error => { if (current) setFailure(error instanceof Error ? error.message : '会话恢复失败。') })
    return () => { current = false }
  }, [restoreId, restoreTry])

  function startNew() {
    if (inFlight.current) return
    remember(); setRestoreId(undefined); setConversationId(undefined); setMessages([]); setJobs([])
    setAttempt(null); setFailure(''); setDraft(''); setHasConnected(false); input.current?.focus()
  }

  async function submit(text: string, requestId = crypto.randomUUID() as string) {
    if (!text.trim() || text.length > 4000 || inFlight.current || restoreId) return
    inFlight.current = true
    setPending(true)
    setFailure(''); setAttempt({ text, id: requestId }); setDraft('')
    try {
      const reply = await sendMessage(text, requestId, conversationId)
      setConversationId(reply.conversation_id)
      remember(reply.conversation_id)
      setJobs(previous => [...new Set([...previous, ...reply.job_ids])])
      setHasConnected(true)
      setMessages(previous => [...previous, { role: 'user', text }, { role: 'assistant', text: reply.assistant_message }])
      setAttempt(null)
    } catch (error) {
      setFailure(error instanceof Error ? error.message : '请求失败，请重试。')
    } finally {
      inFlight.current = false
      setPending(false)
      input.current?.focus()
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submit(draft)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
      event.preventDefault()
      void submit(draft)
    }
  }

  const connectionLabel = failure ? '请求失败' : restoreId ? '恢复会话中' : pending ? '请求中' : hasConnected ? '会话已保存' : '新对话'
  const visible = attempt ? [...messages, { role: 'user' as const, text: attempt.text }] : messages

  return (
    <div className="app-shell">
      <header className="page-header">
        <a className="brand" href="/" aria-label="Protein Chat 首页">
          <span className="brand-mark" aria-hidden="true">P<span>·</span></span>
          <span>Protein Chat<small>对话式蛋白质结构预测</small></span>
        </a>
        <span className="stage-label">{faultDemo ? '隔离故障演示' : '本地工作台'}</span>
      </header>

      <main>
        <section className="intro" aria-labelledby="page-title">
          <p className="eyebrow">MRes · LOCAL PROTOTYPE</p>
          <h1 id="page-title">从一句对话开始。</h1>
          <p className="intro-copy">输入一条蛋白质序列，选择 ESMFold2 或 Protenix。也可以分两条消息告诉我。</p>
        </section>

        <section className="chat-panel" aria-labelledby="chat-title">
          <div className="panel-header">
            <div><h2 id="chat-title">对话</h2><span className="mode-badge">{faultDemo ? '测试替身 · 不调用 LLM' : 'DeepSeek · 工具调用'}</span></div>
            <button className="new-chat" type="button" disabled={pending} onClick={startNew}>新对话</button>
            <span className={`connection-state ${failure ? 'failed' : ''}`} role="status">
              <span className={pending ? 'status-dot active' : 'status-dot'} />{connectionLabel}
            </span>
          </div>

          <div className="scope-note">{faultDemo ? '隔离测试使用临时数据库和预设工具调用，演示执行异常和损坏输出。' : '对话与序列会发送至 DeepSeek。ESMFold2 Real 任务还会把序列发送至后端选定的 OpenProtein 或 Biohub。'} Mock 任务展示公开的泛素示例结构。</div>

          <div className="message-area" role="log" aria-label="聊天记录" aria-live="polite" aria-relevant="additions text">
            {restoreId && !failure && <p role="status">正在恢复聊天记录…</p>}
            {!restoreId && visible.length === 0 && (
              <div className="empty-state">
                <div className="conversation-symbol" aria-hidden="true">↗</div>
                <h3>发送第一条消息</h3>
                <p>输入自己的消息，或选择一个例子。</p>
                <div className="examples">
                  {[['泛素 · 先发序列', `请预测这条序列：\n${ubiquitin}`], ['English · Protenix', `Use Protenix to predict this sequence:\n${ubiquitin}`]].map(([label, example]) => (
                    <button key={label} type="button" onClick={() => { setDraft(example); input.current?.focus() }}>{label}<span aria-hidden="true">↗</span></button>
                  ))}
                </div>
              </div>
            )}
            {visible.map((message, index) => (
              <article key={index} className={`message ${message.role}`}>
                <span className="message-author">{message.role === 'user' ? '你 / You' : '助手 / Assistant'}</span>
                <p>{message.text}</p>
              </article>
            ))}
            {pending && <div className="pending-message"><span className="spinner" aria-hidden="true" />正在等待助手回复…</div>}
            <div ref={endOfMessages} />
          </div>

          {failure && <div className="error-notice" role="alert"><span>{failure}</span>
            {restoreId ? <button type="button" onClick={() => setRestoreTry(n => n + 1)}>重试恢复</button>
              : attempt && <button type="button" onClick={() => void submit(attempt.text, attempt.id)} disabled={pending}>重试上条消息</button>}
          </div>}

          <form className="composer" onSubmit={handleSubmit} aria-busy={pending}>
            <label htmlFor="message">你的消息</label>
            <textarea id="message" ref={input} rows={3} maxLength={4000} value={draft}
              onChange={event => setDraft(event.target.value)} onKeyDown={handleKeyDown}
              placeholder="输入消息 / Type a message…" aria-describedby="composer-help" />
            <div className="composer-bottom">
              <span id="composer-help">Enter 发送 · Shift + Enter 换行 <span className="character-count">{draft.length}/4000</span></span>
              <button className="send-button" type="submit" disabled={pending || Boolean(restoreId) || !draft.trim()}>{pending ? '发送中…' : '发送消息'}<span aria-hidden="true">↑</span></button>
            </div>
          </form>
        </section>

        {conversationId && jobs.length > 0 && <JobPanel key={conversationId} cid={conversationId} ids={jobs} />}
        <footer className="page-footer"><span>会话与任务保存在本机 · 刷新可恢复</span><span>单链 · 1–500 aa</span></footer>
      </main>
    </div>
  )
}
