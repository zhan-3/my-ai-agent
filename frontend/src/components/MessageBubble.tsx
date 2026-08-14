import { agentOf } from '@/lib/agents'
import { isTripAnswer } from '@/lib/trip'
import type { ChatMessage } from '@/hooks/useChat'
import TripCard from '@/components/TripCard'
import StatsCard from '@/components/StatsCard'

// 单条消息气泡：用户 / 晓问（带子 Agent 徽章）。
// SSE 阶段进度已替代打字机模拟（真实等待有实时反馈），答案到达即整段渲染。
export default function MessageBubble({ msg }: { msg: ChatMessage }) {
  // slice 1：后端带结构化 plan 即行程；旧后端回退到「意图+文本特征」判断
  const isTrip = msg.role === 'ai' && (msg.plan != null || isTripAnswer(msg.intent ?? '', msg.text))
  const hasStats = msg.role === 'ai' && msg.stats != null

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-2.5 text-sm text-primary-foreground">
          {msg.text}
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
          <TripCard text={msg.text} plan={msg.plan} />
        </div>
      ) : hasStats ? (
        <div className="max-w-[85%]">
          <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm">
            <div className="mb-1.5 font-medium">📊 差旅画像</div>
            <StatsCard stats={msg.stats!} />
          </div>
        </div>
      ) : (
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm">
          {msg.text}
        </div>
      )}
    </div>
  )
}
