import { useCallback, useEffect, useState } from 'react'
import { getStats, type TravelStats } from '@/api/stats'
import { getStoredToken } from '@/lib/storage'
import { Badge } from '@/components/ui/badge'
import StatsCard from '@/components/StatsCard'

const EMPTY: TravelStats = {
  has_data: false,
  trips: 0,
  total_days: 0,
  avg_days: 0,
  skipped_days: 0,
  top_cities: [],
  years: [],
  upcoming_trips: 0,
}

// 差旅画像面板：fetch /api/stats（确定性聚合，零 LLM）后交给 StatsCard 渲染
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
        <div className="text-xs text-muted-foreground">
          {stats.upcoming_trips > 0
            ? `暂无已发生行程，已规划 ${stats.upcoming_trips} 次（未来）`
            : '暂无行程记录，规划后自动统计'}
        </div>
      ) : (
        <StatsCard stats={stats} />
      )}
    </div>
  )
}
