export type Message = { role: 'user' | 'assistant'; text: string }
type ChatReply = { conversation_id: string; assistant_message: string; chat_mode: 'llm'; job_ids: string[]; outcome: string }
type Conversation = { conversation_id: string; messages: Message[]; job_ids: string[] }

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null
const ids = (v: unknown) => Array.isArray(v) && v.every(x => typeof x === 'string')
export type Job = {
  id: string; conversation_id: string; model: 'esmfold2' | 'protenix'; model_version: string
  mode: 'mock' | 'real'; status: 'queued' | 'running' | 'succeeded' | 'failed'; length: number; parameters?: {execution?: string}
  created_at: string; started_at: string | null; finished_at: string | null; fixture_source: string | null
  error: string | null; error_message: string | null; result_available: boolean; download_name: string | null; sha256: string | null
}
export const jobPath = (cid: string, id: string, structure = false, download = false) =>
  `/api/jobs/${encodeURIComponent(id)}${structure ? '/structure' : ''}?conversation_id=${encodeURIComponent(cid)}${download ? '&download=true' : ''}`

export async function getJob(cid: string, id: string): Promise<Job> {
  const d = await request(jobPath(cid, id), { cache: 'no-store' }, 8000)
  if (!isObject(d) || d.id !== id || d.conversation_id !== cid || !['esmfold2','protenix'].includes(String(d.model))
      || !['queued','running','succeeded','failed'].includes(String(d.status)) || !['mock','real'].includes(String(d.mode))
      || typeof d.result_available !== 'boolean' || d.result_available !== (d.status === 'succeeded')
      || typeof d.length !== 'number' || typeof d.model_version !== 'string') throw new ChatError('任务响应无效，请重试。')
  return d as Job
}
export class ChatError extends Error {}

async function request(path: string, init: RequestInit, timeoutMs: number): Promise<unknown> {
  const timeout = AbortSignal.timeout(timeoutMs)
  try {
    const response = await fetch(path, { ...init, signal: timeout })
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null)
      if (isObject(body) && isObject(body.error) && typeof body.error.message === 'string') {
        throw new ChatError(body.error.message)
      }
      throw new ChatError('服务暂不可用，请确认 FastAPI 后端已启动，然后重试。')
    }
    return await response.json()
  } catch (error) {
    if (error instanceof ChatError) throw error
    if (timeout.aborted) throw new ChatError(`请求超过 ${timeoutMs / 1000} 秒，请检查连接后重试。`)
    if (error instanceof SyntaxError) throw new ChatError('后端响应不是有效 JSON，请检查后端服务。')
    throw new ChatError('无法连接后端，请确认 FastAPI 正在运行。')
  }
}

export async function sendMessage(message: string, requestId: string, conversationId?: string): Promise<ChatReply> {
  const data = await request('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, request_id: requestId, conversation_id: conversationId }) }, 70_000)
  if (!isObject(data) || typeof data.conversation_id !== 'string' || data.chat_mode !== 'llm' ||
      !ids(data.job_ids) || typeof data.outcome !== 'string' || typeof data.assistant_message !== 'string' || !data.assistant_message.trim()) {
    throw new ChatError('无法识别聊天回复，请确认正在运行本轮后端。')
  }
  return data as ChatReply
}

export async function loadConversation(id: string): Promise<Conversation> {
  const data = await request(`/api/conversations/${encodeURIComponent(id)}`, {}, 8_000)
  if (!isObject(data) || data.conversation_id !== id || !ids(data.job_ids) || !Array.isArray(data.messages) ||
      !data.messages.every(m => isObject(m) && (m.role === 'user' || m.role === 'assistant') && typeof m.text === 'string')) {
    throw new ChatError('会话记录格式不正确。可重试恢复，或开始新对话。')
  }
  return data as Conversation
}
