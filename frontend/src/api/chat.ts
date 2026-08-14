import { request, ApiError } from './client'
import type { ChatResponse, TripPlan, TravelStats } from './contract'

export { ApiError }
export type { ChatResponse }

export function sendMessage(text: string, token: string): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', { method: 'POST', body: { user_input: text }, token })
}

// ---- SSE 流式聊天（POST /api/chat/stream，阶段事件 + done） ----

export interface StreamEvent {
  type: 'stage' | 'done' | 'error'
  status?: string // start | intent | working | done
  intent?: string // 意图名；__merge__ 表示并行汇总
  resolved?: string
  answer?: string
  reason?: string
  plan?: TripPlan | null
  stats?: TravelStats | null
  message?: string
}

// 纯函数：SSE 缓冲 → 完整事件列表 + 残留（处理跨 chunk 边界、坏帧忽略）
export function parseSSEBuffer(buffer: string): { events: StreamEvent[]; rest: string } {
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  const events: StreamEvent[] = []
  for (const part of parts) {
    const dataLine = part.split('\n').find((l) => l.startsWith('data:'))
    if (!dataLine) continue
    try {
      events.push(JSON.parse(dataLine.slice(5).trim()) as StreamEvent)
    } catch {
      // 坏帧忽略
    }
  }
  return { events, rest }
}

// 流式聊天：fetch 读 SSE，逐事件回调；done 事件返回最终结果；error 事件抛错
export async function streamChat(
  text: string,
  token: string,
  onEvent: (e: StreamEvent) => void,
): Promise<ChatResponse> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ user_input: text }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body?.detail)
  }
  if (!res.body) throw new Error('网络错误，请确认服务已启动')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: ChatResponse | null = null
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, rest } = parseSSEBuffer(buffer)
    buffer = rest
    for (const e of events) {
      onEvent(e)
      if (e.type === 'done' && e.answer != null) {
        final = {
          answer: e.answer,
          intent: e.intent ?? '',
          reason: e.reason ?? '',
          plan: e.plan ?? null,
          stats: e.stats ?? null,
        }
      } else if (e.type === 'error') {
        throw new Error(e.message || '服务暂时不可用')
      }
    }
  }
  if (!final) throw new Error('网络错误，请确认服务已启动')
  return final
}
