import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import TripCard from '@/components/TripCard'
import { isTripAnswer, parseTrip } from '@/lib/trip'

const TRIP_TEXT = [
  '📋 上海→北京 4 天差旅行程',
  '💡 安排理由：',
  '  · 按差旅标准选择住宿',
  '  · 会议集中在上午',
  '【10月8日 周四】',
  '  交通：高铁 G2 次',
  '  住宿：汉庭（协议价）',
  '  活动：上午开项目会',
  '【10月9日 周五】',
  '  活动：拜访客户',
  '🌤️ 目的地天气提醒：晴，20°C',
].join('\n')

describe('TripCard 行程卡片（文本格式解析 → 结构化渲染）', () => {
  it('isTripAnswer：行程规划 + 含【 才判为行程', () => {
    expect(isTripAnswer('行程规划', '📋 x\n【10月8日】')).toBe(true)
    expect(isTripAnswer('行程规划', '普通回答')).toBe(false)
    expect(isTripAnswer('知识问答', '📋 x\n【10月8日】')).toBe(false)
  })

  it('parseTrip：纯函数解析出 summary/reasons/days/reminders', () => {
    const t = parseTrip(TRIP_TEXT)
    expect(t.summary).toBe('上海→北京 4 天差旅行程')
    expect(t.reasons).toEqual(['按差旅标准选择住宿', '会议集中在上午'])
    expect(t.days).toHaveLength(2)
    expect(t.days[0].date).toBe('10月8日 周四')
    expect(t.days[0].rows).toContainEqual({ label: '交通', text: '高铁 G2 次' })
    expect(t.days[0].rows).toContainEqual({ label: '活动', text: '上午开项目会' })
    expect(t.reminders[0].text).toContain('目的地天气提醒')
  })

  it('渲染：摘要 / 理由 / 逐日卡片（日期+行） / 提醒', () => {
    render(<TripCard text={TRIP_TEXT} />)
    expect(screen.getByText(/上海→北京 4 天差旅行程/)).toBeInTheDocument()
    expect(screen.getByText('💡 安排理由')).toBeInTheDocument()
    expect(screen.getByText(/10月8日 周四/)).toBeInTheDocument()
    expect(screen.getByText('高铁 G2 次')).toBeInTheDocument()
    expect(screen.getByText(/目的地天气提醒/)).toBeInTheDocument()
  })

  it('plan 模式：结构化数据驱动渲染（slice 1），预算/天气从文本附加', () => {
    const plan = {
      summary: '北京出差 4 天',
      reasons: ['按差旅标准选住宿'],
      date_is_vague: false,
      days: [
        { date: '2026-10-08', transport: '高铁 G1', hotel: '汉庭', activities: ['上午开会'], notes: '带电脑' },
        { date: '2026-10-09', transport: '高铁 G2', hotel: '无（当晚返程）', activities: ['拜访客户'], notes: '' },
      ],
    }
    const text =
      '📋 北京出差 4 天\n【2026-10-08】\n  交通：高铁 G1\n  住宿：汉庭\n  活动：上午开会\n  备注：带电脑\n【2026-10-09】\n  交通：高铁 G2\n  住宿：无（当晚返程）\n  活动：拜访客户\n\n💰 费用估算（参考价，以实际出票为准）：\n· 合计：约 3000 元\n\n🌤️ 目的地天气提醒：北京 晴 10°C'

    render(<TripCard text={text} plan={plan} />)
    // 结构化渲染（activities → 活动行）
    expect(screen.getByText(/北京出差 4 天/)).toBeInTheDocument()
    expect(screen.getByText('上午开会')).toBeInTheDocument()
    expect(screen.getByText('带电脑')).toBeInTheDocument()
    // 附加块从文本补上（plan 里没有预算/天气）
    expect(screen.getByText(/合计：约 3000 元/)).toBeInTheDocument()
    expect(screen.getByText(/目的地天气提醒：北京 晴/)).toBeInTheDocument()
    // plan 模式不走文本解析（文本里若有与 plan 不一致的正文也不渲染）
    expect(screen.queryByText('高铁 G2 次')).not.toBeInTheDocument()
  })

  it('预算块：文本回退模式单独成块展示', () => {
    render(<TripCard text={TRIP_TEXT + '\n\n💰 费用估算（参考价）：\n· 合计：约 5000 元'} />)
    expect(screen.getByText(/合计：约 5000 元/)).toBeInTheDocument()
  })
})
