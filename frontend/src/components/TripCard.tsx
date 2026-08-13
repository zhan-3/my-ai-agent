import { Card, CardContent } from '@/components/ui/card'
import { parseTrip, type ParsedTrip } from '@/lib/trip'

// 行程卡片：数据驱动渲染（来源：旧 renderTripCard 的展示结构，解析收口到 lib/trip 纯函数）
// slice 1 后端返回结构化 plan 后，本组件改为直接吃 plan（解析函数保留作回退兜底）

const ROW_CLS: Record<string, string> = {
  交通: 'text-blue-600 dark:text-blue-400',
  住宿: 'text-amber-600 dark:text-amber-400',
  活动: 'text-emerald-600 dark:text-emerald-400',
  用餐: 'text-rose-600 dark:text-rose-400',
  备注: 'text-muted-foreground',
}

export default function TripCard({ text }: { text: string }) {
  const trip: ParsedTrip = parseTrip(text)

  return (
    <Card className="border-primary/20">
      <CardContent className="space-y-3 pt-4">
        {trip.summary && <div className="font-semibold">📋 {trip.summary}</div>}
        {trip.reasons.length > 0 && (
          <div className="text-sm">
            <div className="font-medium">💡 安排理由</div>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
              {trip.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </div>
        )}
        {trip.days.map((d, i) => (
          <div key={i} className="rounded-lg border bg-muted/30 p-3">
            <div className="mb-2 text-sm font-medium">📅 {d.date}</div>
            <div className="space-y-1">
              {d.rows.map((r, j) =>
                r.label ? (
                  <div key={j} className="flex gap-2 text-sm">
                    <span className={`shrink-0 font-medium ${ROW_CLS[r.label] ?? ''}`}>{r.label}</span>
                    <span>{r.text}</span>
                  </div>
                ) : (
                  <div key={j} className="text-sm">
                    {r.text}
                  </div>
                ),
              )}
            </div>
          </div>
        ))}
        {trip.reminders.map((r, i) => (
          <div key={`r${i}`} className="text-sm text-muted-foreground">
            {r.text}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
