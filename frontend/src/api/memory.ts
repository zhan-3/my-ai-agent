import { request } from './client'
import type { KnowledgeSource, MemorySnapshot } from './contract'

export type { MemorySnapshot }

export function getMemory(token: string): Promise<MemorySnapshot> {
  return request<MemorySnapshot>('/api/memory', { token })
}

export function cancelTrip(token: string, tripId: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/trips/${tripId}/cancel`, { method: 'POST', token })
}

export interface HistoryMessage {
  role: 'user' | 'ai'
  text: string
  sources?: KnowledgeSource[]
}

export function getMessages(token: string, conversationId: string): Promise<{ messages: HistoryMessage[] }> {
  return request<{ messages: HistoryMessage[] }>(
    `/api/messages?conversation_id=${encodeURIComponent(conversationId)}`,
    { token },
  )
}
