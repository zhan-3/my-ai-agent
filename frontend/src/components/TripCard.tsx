import { useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { parseTrip, planToParsed, type TripPlan } from '@/lib/trip'

// 行程卡片：数据驱动渲染。
// slice 1：后端 /api/chat 带结构化 plan → 直接按 plan 渲染；旧后端/缺 plan → 解析文本回退。
// 两种来源先归一化成同一渲染形状（planToParsed / parseTrip），卡片只画一种结构；
// 💰预算/🌤️天气/📅日期提示等附加块刻意留在文本里，无论哪种来源都从文本解析补上。

// 行标签语义色：主题 token（--row-*），跨浅/深色稳定（备注直接用 muted-foreground）
const ROW_CLS: Record<string, string> = {
  交通: 'text-[color:var(--row-transport)]',
  住宿: 'text-[color:var(--row-hotel)]',
  活动: 'text-[color:var(--row-activity)]',
  用餐: 'text-[color:var(--row-meal)]',
}

export default function TripCard({ text, plan }: { text: string; plan?: TripPlan | null }) {
  const trip = useMemo(() => {
    const parsed = parseTrip(text)
    if (!plan) return parsed // 文本回退：旧后端/无 plan
    return {
      ...planToParsed(plan),
      budget: parsed.budget, // 附加块不在 plan 里，从文本取
      reminders: parsed.reminders,
    }
  }, [text, plan])

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
                    <span className={`shrink-0 font-medium ${ROW_CLS[r.label] ?? 'text-muted-foreground'}`}>
                      {r.label}
                    </span>
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
        {trip.budget && (
          <div className="whitespace-pre-wrap rounded-lg bg-muted/50 p-3 text-sm">{trip.budget}</div>
        )}
        {trip.reminders.map((r, i) => (
          <div key={`r${i}`} className="text-sm text-muted-foreground">
            {r.text}
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
