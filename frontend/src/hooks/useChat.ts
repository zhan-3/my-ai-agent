import { useCallback, useRef, useState } from 'react'
import { sendMessage, type ChatResponse } from '@/api/chat'
import { ApiError } from '@/api/client'
import { getStoredToken } from '@/lib/storage'

export interface ChatMessage {
  role: 'user' | 'ai'
  text: string
  intent?: string
}

const NETWORK_FALLBACK = '⚠️ 网络错误，请确认后端已启动。'

// 聊天状态：消息列表 + 发送流（busy 防重复提交；401 登出；网络错误降级文案）
export function useChat({ onUnauthorized }: { onUnauthorized: () => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false) // ref 同步置位：同轮两次 send 也能拦住（useState 闭包做不到）

  const send = useCallback(
    async (text: string): Promise<ChatResponse | null> => {
      if (busyRef.current) return null
      const t = text.trim()
      if (!t) return null
      busyRef.current = true
      setBusy(true)
      setMessages((m) => [...m, { role: 'user', text: t }])
      try {
        const res = await sendMessage(t, getStoredToken() ?? '')
        setMessages((m) => [...m, { role: 'ai', text: res.answer, intent: res.intent }])
        return res
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          onUnauthorized() // 登录失效：登出，不追加错误消息
          return null
        }
        setMessages((m) => [...m, { role: 'ai', text: NETWORK_FALLBACK }])
        return null
      } finally {
        busyRef.current = false
        setBusy(false)
      }
    },
    [onUnauthorized],
  )

  return { messages, busy, send }
}
