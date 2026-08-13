import { request } from './client'
import type { TripPlan } from '@/lib/trip'

// 与后端 webapp.ChatResponse 对应；plan 为 slice 1 新增（行程时非空，其余为 null/缺省）
export interface ChatResponse {
  answer: string
  intent: string
  reason: string
  plan?: TripPlan | null
}

export function sendMessage(text: string, token: string): Promise<ChatResponse> {
  return request<ChatResponse>('/api/chat', { method: 'POST', body: { user_input: text }, token })
}
