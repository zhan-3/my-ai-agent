import { agentOf } from '@/lib/agents'
import { isTripAnswer } from '@/lib/trip'
import type { ChatMessage } from '@/hooks/useChat'
import TripCard from '@/components/TripCard'
import StatsCard from '@/components/StatsCard'
import HistoryCard from '@/components/HistoryCard'
import type { KnowledgeSource } from '@/api/contract'
import { useState } from 'react'

// 单条消息气泡：用户 / 晓问（带子 Agent 徽章）。
// SSE 阶段进度已替代打字机模拟（真实等待有实时反馈），答案到达即整段渲染。
function Sources({ sources }: { sources: KnowledgeSource[] }) {
  const [open, setOpen] = useState(false)
  if (!sources.length) return null
  const unique = sources.filter((source, index) => sources.findIndex((item) => item.source === source.source) === index)
  return (
    <>
      <button type="button" className="mt-2 text-xs text-primary underline-offset-2 hover:underline" onClick={() => setOpen(true)}>
        查看政策原文（{unique.length} 个来源）
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-background p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold">📄 政策与知识库原文</h2>
              <button type="button" className="rounded-md border px-2 py-1 text-sm hover:bg-muted" onClick={() => setOpen(false)}>
                关闭
              </button>
            </div>
            <div className="space-y-4">
              {unique.map((source) => (
                <section key={source.evidence_id} className="rounded-lg border p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <strong className="text-foreground">{source.source}</strong>
                    {source.section && <span>{source.section}</span>}
                    {source.similarity != null && <span>相关度 {(source.similarity * 100).toFixed(0)}%</span>}
                  </div>
                  <p className="whitespace-pre-wrap text-sm leading-6">{source.text || '暂无原文片段'}</p>
                </section>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export default function MessageBubble({ msg }: { msg: ChatMessage }) {
  // slice 1：后端带结构化 plan 即行程；旧后端回退到「意图+文本特征」判断
  const isTrip = msg.role === 'ai' && (msg.plan != null || isTripAnswer(msg.intent ?? '', msg.text))
  const hasStats = msg.role === 'ai' && msg.stats != null
  const hasHistory = msg.role === 'ai' && msg.history != null && msg.history.itineraries.length > 0

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
      ) : hasHistory ? (
        <div className="max-w-[85%]">
          <div className="rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm">
            <HistoryCard history={msg.history!} />
          </div>
        </div>
      ) : (
        <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5 text-sm">
          {msg.text}
          <Sources sources={msg.sources ?? []} />
        </div>
      )}
    </div>
  )
}
