import { useEffect, useState } from 'react'
import { agentOf } from '@/lib/agents'
import { isTripAnswer } from '@/lib/trip'
import type { ChatMessage } from '@/hooks/useChat'
import TripCard from '@/components/TripCard'

// 单条消息气泡：用户 / 晓问（带子 Agent 徽章）；AI 普通文本打字机逐字，行程答案整卡渲染
export default function MessageBubble({ msg }: { msg: ChatMessage }) {
  const [shown, setShown] = useState(msg.role === 'user' ? msg.text : '')

  const isTrip = msg.role === 'ai' && isTripAnswer(msg.intent ?? '', msg.text)

  useEffect(() => {
    if (msg.role !== 'ai' || isTrip) {
      setShown(msg.text)
      return
    }
    let i = 0
    const speed = msg.text.length > 350 ? 5 : 10
    const id = setInterval(() => {
      i += 1
      setShown(msg.text.slice(0, i))
      if (i >= msg.text.length) clearInterval(id)
    }, speed)
    return () => clearInterval(id)
  }, [msg, isTrip])

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {shown}
        </div>
      </div>
    )
  }

  const agent = agentOf(msg.intent)
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        晓问
        {msg.intent && (
          <span className="rounded-full border px-2 py-0.5 text-[11px]" title={agent.desc}>
            {agent.icon} {agent.name}
          </span>
        )}
      </div>
      {isTrip ? (
        <div className="max-w-[85%]">
          <TripCard text={msg.text} />
        </div>
      ) : (
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm">
          {shown}
        </div>
      )}
    </div>
  )
}
