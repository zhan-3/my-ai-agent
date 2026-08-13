import { request } from './client'
import type { MemorySnapshot } from './contract'

export type { MemorySnapshot }

export function getMemory(token: string): Promise<MemorySnapshot> {
  return request<MemorySnapshot>('/api/memory', { token })
}
