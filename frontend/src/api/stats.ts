import { request } from './client'
import type { TravelStats } from './contract'

export type { TravelStats }

export function getStats(token: string): Promise<TravelStats> {
  return request<TravelStats>('/api/stats', { token })
}
