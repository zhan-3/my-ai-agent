import { request } from './client'

export interface Preference {
  category: string
  content: string
}

export interface Itinerary {
  start_date?: string
  from_city?: string
  to_city?: string
  duration_days?: number
}

export interface MemorySnapshot {
  preferences: Preference[]
  itineraries: Itinerary[]
}

export function getMemory(token: string): Promise<MemorySnapshot> {
  return request<MemorySnapshot>('/api/memory', { token })
}
