import { useCallback, useEffect, useState } from 'react'
import { getMemory, type MemorySnapshot } from '@/api/memory'
import { getStoredToken } from '@/lib/storage'
import { Badge } from '@/components/ui/badge'
import StatsPanel from '@/components/StatsPanel'
import type { Itinerary } from '@/api/contract'

function ArchiveItem({ itinerary }: { itinerary: Itinerary }) {
  const [expanded, setExpanded] = useState(false)
  const title = itinerary.summary ?? `${itinerary.from_city ?? '?'}→${itinerary.to_city ?? '?'}`
  return (
    <li className="rounded-md bg-background text-xs">
      <button
        type="button"
        className="flex w-full items-start gap-2 p-2 text-left hover:bg-muted"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="shrink-0 font-medium text-primary">{(itinerary.start_date ?? '?').slice(5)}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{title}</span>
          <span className="text-muted-foreground">
            {itinerary.from_city ?? '?'}→{itinerary.to_city ?? '?'} · {itinerary.duration_days ?? '?'}天
          </span>
        </span>
        <span className="text-muted-foreground">{expanded ? '⌃' : '⌄'}</span>
      </button>
      {expanded && (
        <div className="border-t px-2 pb-2 pt-2 text-muted-foreground">
          <div>{itinerary.status ?? '历史'}</div>
          {itinerary.summary && <div className="mt-1 leading-relaxed">{itinerary.summary}</div>}
        </div>
      )}
    </li>
  )
}

// 记忆侧栏：当前账号长期记忆（偏好 + 行程档案），refreshKey 变化时重新拉取
export default function MemorySidebar({ refreshKey }: { refreshKey: number }) {
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
              <ArchiveItem key={i} itinerary={it} />
            ))}
          </ul>
        )}
      </div>
      <StatsPanel refreshKey={refreshKey} />
      <div className="mt-auto text-[11px] leading-relaxed text-muted-foreground">
        💡 左侧是<b>当前账号</b>的长期记忆（Postgres / 内存后端），由子 Agent 自动读写——住宿偏好、
        常驻城市、历史行程都会实时落在这里，下次规划自动生效。
      </div>
    </aside>
  )
}
