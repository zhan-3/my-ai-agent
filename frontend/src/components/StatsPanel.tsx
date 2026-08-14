import { useCallback, useEffect, useState } from 'react'
import { getStats, type TravelStats } from '@/api/stats'
import { getStoredToken } from '@/lib/storage'
import { Badge } from '@/components/ui/badge'

const EMPTY: TravelStats = {
  has_data: false,
  trips: 0,
  total_days: 0,
  avg_days: 0,
  skipped_days: 0,
  top_cities: [],
  years: [],
}

// 差旅画像：确定性聚合（/api/stats，零 LLM）——次数/天数/常去城市/年度趋势
export default function StatsPanel({ refreshKey }: { refreshKey: number }) {
  const [stats, setStats] = useState<TravelStats>(EMPTY)

  const load = useCallback(async () => {
    try {
      setStats(await getStats(getStoredToken() ?? ''))
    } catch {
      // 画像拉取失败不打扰主流程
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
        差旅画像 <Badge variant="secondary">{stats.has_data ? stats.trips : 0} 次</Badge>
      </div>
      {!stats.has_data ? (
        <div className="text-xs text-muted-foreground">暂无行程记录，规划后自动统计</div>
      ) : (
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
        </div>
      )}
    </div>
  )
}
