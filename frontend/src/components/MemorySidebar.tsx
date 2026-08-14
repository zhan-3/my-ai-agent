import { useCallback, useEffect, useState } from 'react'
import { getMemory, type MemorySnapshot } from '@/api/memory'
import { getStoredToken } from '@/lib/storage'
import { Badge } from '@/components/ui/badge'
import StatsPanel from '@/components/StatsPanel'

// 记忆侧栏：当前账号长期记忆（偏好 + 历史行程），refreshKey 变化时重新拉取
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
          历史行程 <Badge variant="secondary">{mem.itineraries.length}</Badge>
        </div>
        {mem.itineraries.length === 0 ? (
          <div className="text-xs text-muted-foreground">暂无行程记录</div>
        ) : (
          <ul className="space-y-1.5">
            {mem.itineraries.map((it, i) => (
              <li key={i} className="flex gap-2 rounded-md bg-background p-2 text-xs">
                <span className="shrink-0 font-medium text-primary">
                  {(it.start_date ?? '?').slice(5)}
                </span>
                <span className="text-muted-foreground">
                  {it.from_city ?? '?'}→{it.to_city ?? '?'} · {it.duration_days ?? '?'}天
                </span>
              </li>
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
