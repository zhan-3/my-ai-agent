// HTTP 契约类型：唯一来源 = 后端 OpenAPI（pnpm gen:api 生成 schema.generated.ts）
// 本文件只是薄别名层：把后端 pydantic 模型名映射成前端语义名。
// 契约变更流程：改后端 contract.py → 重启后端 → pnpm gen:api → 提交生成的 schema。
import type { components } from './schema.generated'

export type AuthResult = components['schemas']['AuthResponse']
export type ChatResponse = components['schemas']['ChatResponse']
export type TripPlan = components['schemas']['TripPlan']
export type TripDay = components['schemas']['TripDay']
export type Preference = components['schemas']['Preference']
export type Itinerary = components['schemas']['Itinerary']
export type MemorySnapshot = components['schemas']['MemorySnapshot']
export type TravelStats = components['schemas']['TravelStats']
export type HistoryResult = components['schemas']['HistoryResult']
export type HistoryItinerary = components['schemas']['HistoryItinerary']
