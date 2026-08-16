import { useCallback, useRef, useState } from 'react'
import { sendMessage, streamChat, type ChatResponse, type StreamEvent } from '@/api/chat'
import { ApiError } from '@/api/client'
import { getStoredToken } from '@/lib/storage'
import type { TripPlan } from '@/lib/trip'
import type { HistoryResult, KnowledgeSource, TravelStats } from '@/api/contract'

export interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  intent?: string
  plan?: TripPlan | null
  stats?: TravelStats | null
  history?: HistoryResult | null
  sources?: KnowledgeSource[]
}

// 实时进度阶段：__start__ 理解中 / __intent__ 已识别意图 / __merge__ 并行汇总 / 其余为子 Agent 意图名
export interface StageItem {
  intent: string
  status: 'working' | 'done'
  resolved?: string
}

const NETWORK_FALLBACK = '⚠️ 网络错误，请确认后端已启动。'

// 纯函数：阶段事件 → 阶段列表（start 重置；intent 替换 start；同一意图去重）
export function applyStage(prev: StageItem[], ev: Pick<StreamEvent, 'status' | 'intent'>): StageItem[] {
  if (ev.status === 'start') return [{ intent: '__start__', status: 'working' }]
  if (ev.status === 'intent') {
    const item: StageItem = { intent: '__intent__', status: 'done', resolved: ev.intent }
    return [...prev.filter((s) => s.intent !== '__start__' && s.intent !== '__intent__'), item]
  }
  const intent = ev.intent ?? ''
  const existing = prev.find((s) => s.intent === intent)
  if (existing) {
    // 原位更新（避免完成时顺序抖动）
    return prev.map((s) =>
      s.intent === intent ? { intent, status: ev.status === 'done' ? 'done' : 'working' } : s,
    )
  }
  return [...prev, { intent, status: ev.status === 'done' ? 'done' : 'working' }]
}

// 聊天状态：SSE 流式（阶段进度 + done）为主，旧后端（404）回退 POST；busy 防重；401 登出
export function useChat({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [stages, setStages] = useState<StageItem[]>([])
  const busyRef = useRef(false) // ref 同步置位：同轮两次 send 也能拦住（useState 闭包做不到）

  const append = useCallback((msg: ChatMessage) => {
    setMessages((m) => [...m, msg])
  }, [])

  const send = useCallback(
    async (text: string): Promise<ChatResponse | null> => {
      if (busyRef.current) return null
      const t = text.trim()
      if (!t) return null
      busyRef.current = true
      setBusy(true)
      setStages([{ intent: '__start__', status: 'working' }])
      append({ role: 'user', text: t })
      const token = getStoredToken() ?? ''
      try {
        const res = await streamChat(t, token, (ev) => {
          if (ev.type === 'stage') setStages((prev) => applyStage(prev, ev))
        })
        append({
          role: 'ai',
          text: res.answer,
          intent: res.intent,
          plan: res.plan ?? null,
          stats: res.stats ?? null,
          history: res.history ?? null,
          ...(res.sources?.length ? { sources: res.sources } : {}),
        })
        return res
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          onUnauthorized() // 登录失效：登出，不追加错误消息
          return null
        }
        if (e instanceof ApiError && e.status === 404) {
          // 旧后端没有 /api/chat/stream：回退 POST /api/chat（行为与旧前端一致）
          try {
            const res = await sendMessage(t, token)
            append({
              role: 'ai',
              text: res.answer,
              intent: res.intent,
              plan: res.plan ?? null,
              stats: res.stats ?? null,
              history: res.history ?? null,
              ...(res.sources?.length ? { sources: res.sources } : {}),
            })
            return res
          } catch (e2) {
            if (e2 instanceof ApiError && e2.status === 401) {
              onUnauthorized()
              return null
            }
            append({ role: 'ai', text: NETWORK_FALLBACK, plan: null })
            return null
          }
        }
        append({ role: 'ai', text: NETWORK_FALLBACK, plan: null })
        return null
      } finally {
        busyRef.current = false
        setBusy(false)
        setStages([])
      }
    },
    [append, onUnauthorized],
  )

  return { messages, busy, send, stages }
}
