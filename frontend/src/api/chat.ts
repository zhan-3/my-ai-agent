import { request } from './client'

// 与后端 webapp.ChatResponse 对应（slice 1 会加可选 plan 字段，前端向后兼容）
export interface ChatResponse {
  answer: string
  intent: string
  reason: string
}

export function sendMessage(text: string, token: string): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', { method: 'POST', body: { user_input: text }, token })
}
