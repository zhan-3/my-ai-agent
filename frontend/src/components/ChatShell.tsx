import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useChat, type StageItem } from '@/hooks/useChat'
import { AGENTS, SUGGESTIONS, agentOf } from '@/lib/agents'
import MemorySidebar from '@/components/MemorySidebar'
import MessageBubble from '@/components/MessageBubble'
import ThemeToggle from '@/components/ThemeToggle'

function stageLabel(s: StageItem): string {
  switch (s.intent) {
    case '__start__':
      return '正在理解你的请求…'
    case '__intent__':
      return `已识别意图：${AGENTS[s.resolved ?? ''] ? agentOf(s.resolved).name : '…'}`
    case '__merge__':
      return s.status === 'done' ? '并行结果汇总完成' : '汇总并行结果…'
    default:
      return `${agentOf(s.intent).icon} ${agentOf(s.intent).name}${s.status === 'done' ? '完成' : '处理中…'}`
  }
}

// 主界面：记忆侧栏 + 聊天区（欢迎语 / 消息流 / SSE 阶段进度 / 快捷提问 / 输入框）
export default function ChatShell({
  username,
  onLogout,
}: {
  username: string | null
  onLogout: () => void
}) {
  const { messages, busy, send, stages, startNewConversation } = useChat({ onUnauthorized: onLogout })
  const [input, setInput] = useState('')
  const [memTick, setMemTick] = useState(0) // 回复成功后 +1，触发记忆侧栏刷新

  async function handleSend(text?: string) {
    const t = (text ?? input).trim()
    if (!t || busy) return
    setInput('')
    const res = await send(t)
    if (res) setMemTick((k) => k + 1) // 仅成功回复后刷新记忆（偏好/行程可能已更新）
  }

  return (
    <div className="flex h-screen">
      <MemorySidebar refreshKey={memTick} />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <div>
            <h1 className="text-base font-bold">
              晓问 <span className="text-primary">·</span> 差旅出行助手
            </h1>
            <p className="text-xs text-muted-foreground">多 Agent 智能出行助手｜规划 · 记忆 · 联网 · 知识</p>
          </div>
          {username && (
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="sm" disabled={busy} onClick={startNewConversation}>
                新对话
              </Button>
              <ThemeToggle />
              <Button variant="ghost" size="sm" onClick={onLogout}>
                {username} ｜ 退出
              </Button>
            </div>
          )}
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto p-6" data-testid="chat-scroll">
          {messages.length === 0 && (
            <div className="mx-auto max-w-md pt-10 text-center">
              <div className="text-xl font-semibold">你好，我是晓问 👋</div>
              <p className="mt-2 text-sm text-muted-foreground">
                你的企业差旅助手。背后是 <b>多 Agent 协作</b>：行程规划、偏好记忆、历史查询、知识库
                （RAG）、联网查询（工具调用）各司其职，共享你的长期记忆。
              </p>
            </div>
          )}
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}
          {busy && stages.length > 0 && (
            <div className="space-y-1.5" data-testid="stages">
              {stages.map((s, i) => (
                <div
                  key={s.intent + i}
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                >
                  {s.status === 'working' ? (
                    <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-primary" />
                  ) : (
                    <span className="text-[color:var(--success)]">✓</span>
                  )}
                  <span>{stageLabel(s)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t p-4">
          <div className="mb-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                disabled={busy}
                className="rounded-full border px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                onClick={() => void handleSend(s)}
              >
                {s}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Input
              value={input}
              placeholder="输入差旅问题，回车发送…"
              disabled={busy}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') void handleSend()
              }}
            />
            <Button disabled={busy} onClick={() => void handleSend()}>
              {busy ? '思考中…' : '发送'}
            </Button>
          </div>
        </div>
      </main>
    </div>
  )
}
