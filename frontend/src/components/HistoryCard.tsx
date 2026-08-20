import type { HistoryItinerary, HistoryResult } from '@/api/contract'
import { Badge } from '@/components/ui/badge'

// 历史行程卡片：聊天消息带 history 结构化结果时渲染。
// 每条行程显示 日期/城市/天数 + status 标签（时空语义三态）+ 摘要截断。
// 未来规划（direction=计划）用同组件，标题/标签颜色区分。
const STATUS_STYLE: Record<string, string> = {
  历史: 'border-border text-muted-foreground',
  进行中: 'border-primary/40 text-primary',
  已规划: 'border-dashed border-primary/50 text-primary',
}

function TripRow({ it }: { it: HistoryItinerary }) {
  return (
    <div className="rounded-md bg-background p-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-primary">{it.start_date ?? '日期待定'}</span>
        <span className="text-muted-foreground">
          {it.from_city ?? '?'} → {it.to_city ?? '?'}
        </span>
        {it.duration_days != null && <span className="text-muted-foreground">{it.duration_days} 天</span>}
        <Badge variant="outline" className={STATUS_STYLE[it.status ?? '历史'] ?? ''}>
          {it.status ?? '历史'}
        </Badge>
      </div>
      {it.summary && (
        <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">{it.summary}</div>
      )}
    </div>
  )
}

// 历史查询结果卡片：纯展示（数据来自聊天消息的 history 字段）
export default function HistoryCard({ history }: { history: HistoryResult }) {
  const isPlan = history.direction === '计划'
  const isAll = history.direction === '全部'
  const title = isPlan ? '📅 已规划的行程' : isAll ? '📋 最近行程' : '🗂️ 历史行程'
  return (
    <div className="space-y-1.5 text-xs">
      <div className="mb-0.5 font-medium">
        {title}
        {history.itineraries.length > 0 && (
          <span className="ml-1 text-muted-foreground">（{history.itineraries.length} 条）</span>
        )}
      </div>
      {history.itineraries.map((it, i) => (
        <TripRow key={`${it.start_date}-${it.from_city}-${it.to_city}-${i}`} it={it} />
      ))}
      {history.preferences.length > 0 && (
        <div className="rounded-md bg-muted p-2 text-muted-foreground">
          💡 记忆偏好：{history.preferences.map((p) => `${p.category} ${p.content}`).join('；')}
        </div>
      )}
    </div>
  )
}
