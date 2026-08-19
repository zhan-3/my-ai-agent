import { useCallback, useEffect, useState } from 'react'
import { cancelTrip, getMemory, type MemorySnapshot } from '@/api/memory'
import { getStoredToken } from '@/lib/storage'
import { Badge } from '@/components/ui/badge'
import StatsPanel from '@/components/StatsPanel'
import type { Itinerary } from '@/api/contract'

// 单个行程档案：一行摘要 + 右侧「箭头跳转续聊」与「叉号取消」两个操作；点击展开看详情。
function ArchiveItem({
  itinerary,
  onContinue,
  onCancel,
}: {
  itinerary: Itinerary
  onContinue?: (it: Itinerary) => void
  onCancel?: (it: Itinerary) => Promise<void>
}) {
  const [expanded, setExpanded] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const route = `${itinerary.from_city ?? '?'}→${itinerary.to_city ?? '?'}`
  const title = itinerary.summary ?? route

  async function handleCancel() {
    if (cancelling || !onCancel) return
    setCancelling(true)
    try {
      await onCancel(itinerary)
    } finally {
      setCancelling(false)
    }
  }

  return (
    <li className="rounded-md bg-background text-xs">
      <div className="flex items-center gap-1 p-1.5">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-start gap-2 rounded p-1 text-left hover:bg-muted"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <span className="shrink-0 font-medium text-primary">{(itinerary.start_date ?? '?').slice(5)}</span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{title}</span>
            <span className="text-muted-foreground">
              {route} · {itinerary.duration_days ?? '?'}天
              {itinerary.people_count ? ` · ${itinerary.people_count}人` : ''}
            </span>
          </span>
          <span className="shrink-0">
            <Badge variant="secondary">{itinerary.status ?? '历史'}</Badge>
          </span>
          <span className="text-muted-foreground">{expanded ? '⌃' : '⌄'}</span>
        </button>
        {onContinue && itinerary.conversation_id && (
          <button
            type="button"
            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-primary"
            title="跳到该对话继续"
            aria-label="跳到该对话继续"
            onClick={() => onContinue(itinerary)}
          >
            ↗
          </button>
        )}
        {onCancel && (
          <button
            type="button"
            className="shrink-0 rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            title="取消行程"
            aria-label="取消行程"
            disabled={cancelling}
            onClick={() => void handleCancel()}
          >
            ✕
          </button>
        )}
      </div>
      {expanded && (
        <div className="border-t px-2 pb-2 pt-2 text-muted-foreground">
          {itinerary.purpose && <div className="mt-0.5">出行目的：{itinerary.purpose}</div>}
          {itinerary.return_date && <div className="mt-1">返程日期：{itinerary.return_date}</div>}
          {itinerary.summary && <div className="mt-1.5 leading-relaxed">{itinerary.summary}</div>}
        </div>
      )}
    </li>
  )
}

// 记忆侧栏：当前账号长期记忆（偏好 + 行程档案），refreshKey 变化时重新拉取
export default function MemorySidebar({
  refreshKey,
  onContinue,
}: {
  refreshKey: number
  onContinue?: (it: Itinerary) => void
}) {
  const [mem, setMem] = useState<MemorySnapshot>({ preferences: [], itineraries: [] })

  const load = useCallback(async () => {
    try {
      const data = await getMemory(getStoredToken() ?? '')
      setMem(data)
    } catch {
      // 记忆栏失败不打扰主流程
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const handleCancel = useCallback(
    async (it: Itinerary) => {
      if (it.id == null) return
      try {
        await cancelTrip(getStoredToken() ?? '', it.id)
        await load()
      } catch {
        // 取消失败不打扰主流程（下次刷新即恢复）
      }
    },
    [load],
  )

  return (
    <aside className="hidden w-72 shrink-0 flex-col gap-4 overflow-y-auto border-r bg-muted/30 p-4 md:flex">
      <div className="text-sm font-semibold">🧠 Agent 记忆库</div>
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
          已记住的偏好 <Badge variant="secondary">{mem.preferences.length}</Badge>
        </div>
        {mem.preferences.length === 0 ? (
          <div className="text-xs text-muted-foreground">暂无，聊天后自动记住</div>
        ) : (
          <ul className="space-y-1.5">
            {mem.preferences.map((p, i) => (
              <li key={i} className="flex gap-2 rounded-md bg-background p-2 text-xs">
                <span className="shrink-0 font-medium text-primary">{p.category}</span>
                <span className="text-muted-foreground">{p.content}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
          行程档案 <Badge variant="secondary">{mem.itineraries.length}</Badge>
        </div>
        {mem.itineraries.length === 0 ? (
          <div className="text-xs text-muted-foreground">暂无行程档案，规划后自动保存</div>
        ) : (
          <ul className="space-y-1.5">
            {mem.itineraries.map((it, i) => (
              <ArchiveItem key={it.id ?? i} itinerary={it} onContinue={onContinue} onCancel={handleCancel} />
            ))}
          </ul>
        )}
      </div>
      <StatsPanel refreshKey={refreshKey} />
      <div className="mt-auto text-[11px] leading-relaxed text-muted-foreground">
        💡 这里是<b>当前账号</b>的长期记忆：住宿/餐饮/交通偏好、常驻城市与历史行程由助手自动沉淀，
        下次规划时自动生效。
      </div>
    </aside>
  )
}
