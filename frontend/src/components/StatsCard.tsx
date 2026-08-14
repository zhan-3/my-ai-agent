import type { TravelStats } from '@/api/contract'
import { Badge } from '@/components/ui/badge'

// 差旅画像卡片：纯展示（不拉取数据）——数据由父级传入（记忆面板 fetch / 聊天消息带 stats）
export default function StatsCard({ stats }: { stats: TravelStats }) {
  return (
    <div className="space-y-1.5 text-xs">
      <div className="rounded-md bg-background p-2">
        <span className="text-muted-foreground">累计出差 </span>
        <span className="font-medium text-primary">{stats.total_days}</span>
        <span className="text-muted-foreground"> 天 · 平均每次 </span>
        <span className="font-medium text-primary">{stats.avg_days}</span>
        <span className="text-muted-foreground"> 天</span>
      </div>
      {stats.top_cities.length > 0 && (
        <div className="rounded-md bg-background p-2">
          <div className="mb-1 text-muted-foreground">常去城市</div>
          <div className="flex flex-wrap gap-1">
            {stats.top_cities.map((c, i) => (
              <Badge key={i} variant="outline">
                {String(c.city)} ×{Number(c.count)}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {stats.years.length > 0 && (
        <div className="rounded-md bg-background p-2">
          <div className="mb-1 text-muted-foreground">年度分布</div>
          <div className="flex flex-wrap gap-1">
            {stats.years.map((y, i) => (
              <Badge key={i} variant="secondary">
                {String(y.year)} 年 {Number(y.count)} 次
              </Badge>
            ))}
          </div>
        </div>
      )}
      {stats.skipped_days > 0 && (
        <div className="rounded-md bg-destructive/10 p-2 text-destructive">
          {stats.skipped_days} 条旧记录缺天数，未计入天数统计
        </div>
      )}
      {stats.upcoming_trips > 0 && (
        <div className="rounded-md bg-primary/5 p-2 text-muted-foreground">
          📅 另已规划 {stats.upcoming_trips} 次行程（未来），未计入画像
        </div>
      )}
    </div>
  )
}
