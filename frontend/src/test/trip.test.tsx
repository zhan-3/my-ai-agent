import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import TripCard from '@/components/TripCard'
import { isTripAnswer, parseTrip } from '@/lib/trip'

// 整体结构文本（ADR-0011 后不逐日切块：去程/住宿/返程 + 每日要点）
const TRIP_TEXT = [
  '📋 上海→北京 4 天差旅行程',
  '💡 安排理由：',
  '  · 按差旅标准选择住宿',
  '  · 会议集中在上午',
  '🚄 去程：高铁 G2 次（具体车次以晓问商旅平台实时查询为准）',
  '🏨 住宿：汉庭（协议价）',
  '🍽️ 饮食偏好：不吃辣',
  '🚄 返程：高铁 G3 次（具体车次以晓问商旅平台实时查询为准）',
  '📌 行程安排：',
  '  · 10月8日 抵达后入住酒店；用餐：清淡不辣',
  '  · 10月9日 拜访客户；用餐：清淡不辣',
  '  · 10月10日 返程',
  '🌤️ 目的地天气提醒：晴，20°C',
].join('\n')

// 旧格式逐日文本（历史回看兼容：折叠成 itinerary）
const OLD_TRIP_TEXT = [
  '📋 上海→北京 4 天差旅行程',
  '💡 安排理由：',
  '  · 按差旅标准选择住宿',
  '【10月8日 周四】',
  '  交通：高铁 G2 次',
  '  住宿：汉庭（协议价）',
  '  活动：上午开项目会',
  '【10月9日 周五】',
  '  活动：拜访客户',
  '🌤️ 目的地天气提醒：晴，20°C',
].join('\n')

describe('TripCard 行程卡片（整体文本格式解析 → 结构化渲染）', () => {
  it('isTripAnswer：行程规划 + 含📋（或旧格式【）才判为行程', () => {
    expect(isTripAnswer('行程规划', '📋 x\n🚄 去程：高铁')).toBe(true)
    expect(isTripAnswer('行程规划', '📋 x\n【10月8日】')).toBe(true)
    expect(isTripAnswer('行程规划', '普通回答')).toBe(false)
    expect(isTripAnswer('知识问答', '📋 x\n🚄 去程：高铁')).toBe(false)
  })

  it('parseTrip：整体格式解析出 summary/reasons/rows/itinerary/reminders', () => {
    const t = parseTrip(TRIP_TEXT)
    expect(t.summary).toBe('上海→北京 4 天差旅行程')
    expect(t.reasons).toEqual(['按差旅标准选择住宿', '会议集中在上午'])
    expect(t.rows).toContainEqual({ label: '去程', text: '高铁 G2 次（具体车次以晓问商旅平台实时查询为准）' })
    expect(t.rows).toContainEqual({ label: '住宿', text: '汉庭（协议价）' })
    expect(t.rows).toContainEqual({ label: '返程', text: '高铁 G3 次（具体车次以晓问商旅平台实时查询为准）' })
    expect(t.diet).toBe('🍽️ 饮食偏好：不吃辣')
    expect(t.itinerary).toEqual([
      '10月8日 抵达后入住酒店；用餐：清淡不辣',
      '10月9日 拜访客户；用餐：清淡不辣',
      '10月10日 返程',
    ])
    expect(t.reminders[0].text).toContain('目的地天气提醒')
  })

  it('parseTrip：长差折叠空白日（其余日期一行）', () => {
    const t = parseTrip(
      [
        '📋 去纽约 7 天',
        '🚄 去程：航班（具体航班以晓问商旅平台实时查询为准）',
        '🏨 住宿：当地商务酒店',
        '🍽️ 饮食偏好：不吃辣',
        '🚄 返程：航班（具体航班以晓问商旅平台实时查询为准）',
        '📌 行程安排：',
        '  · 2026-10-08 抵达后入住酒店',
        '  · 2026-10-11 拜访客户',
        '  · 2026-10-14 返程',
        '  · 其余 4 天：继续拜访客户',
        '⏰ 时差提醒：目的地纽约比北京时间晚12小时，建议出发前调整作息。',
      ].join('\n'),
    )
    expect(t.itinerary).toEqual([
      '2026-10-08 抵达后入住酒店',
      '2026-10-11 拜访客户',
      '2026-10-14 返程',
      '其余 4 天：继续拜访客户',
    ])
    expect(t.diet).toBe('🍽️ 饮食偏好：不吃辣')
  })

  it('parseTrip：旧格式逐日块折叠成 itinerary（历史回看兼容）', () => {
    const t = parseTrip(OLD_TRIP_TEXT)
    expect(t.summary).toBe('上海→北京 4 天差旅行程')
    expect(t.itinerary).toEqual([
      '10月8日 周四 交通：高铁 G2 次；住宿：汉庭（协议价）；活动：上午开项目会',
      '10月9日 周五 活动：拜访客户',
    ])
    expect(t.rows).toHaveLength(0)
    expect(t.reminders[0].text).toContain('目的地天气提醒')
  })

  it('渲染：摘要 / 理由 / 整体字段行 / 每日要点 / 提醒', () => {
    render(<TripCard text={TRIP_TEXT} />)
    expect(screen.getByText(/上海→北京 4 天差旅行程/)).toBeInTheDocument()
    expect(screen.getByText('💡 安排理由')).toBeInTheDocument()
    expect(screen.getByText('去程')).toBeInTheDocument()
    expect(screen.getByText('高铁 G2 次（具体车次以晓问商旅平台实时查询为准）')).toBeInTheDocument()
    expect(screen.getByText('📌 行程安排')).toBeInTheDocument()
    expect(screen.getByText(/10月9日 拜访客户/)).toBeInTheDocument()
    expect(screen.getByText(/目的地天气提醒/)).toBeInTheDocument()
  })

  it('plan 模式：结构化数据折叠成整体（去程/住宿/返程/要点），预算/天气从文本附加', () => {
    const plan = {
      summary: '北京出差 4 天',
      reasons: ['按差旅标准选住宿'],
      date_is_vague: false,
      days: [
        { date: '2026-10-08', transport: '高铁 G1', hotel: '汉庭', activities: ['抵达后入住酒店'], notes: '带电脑' },
        { date: '2026-10-09', transport: '', hotel: '', activities: ['拜访客户'], notes: '' },
        { date: '2026-10-10', transport: '高铁 G2', hotel: '无（当晚返程）', activities: ['返程'], notes: '' },
      ],
    }
    const text =
      '📋 北京出差 4 天\n🚄 去程：高铁 G999\n🏨 住宿：假日酒店\n🚄 返程：高铁 G888\n📌 行程安排：\n· 2026-10-08 抵达后入住酒店\n\n💰 费用估算（参考价，以实际出票为准）：\n· 合计：约 3000 元\n\n🌤️ 目的地天气提醒：北京 晴 10°C'

    render(<TripCard text={text} plan={plan} />)
    // 结构化渲染（activities → 要点，transport/hotel → 去程/住宿/返程行）
    expect(screen.getByText(/北京出差 4 天/)).toBeInTheDocument()
    expect(screen.getByText(/拜访客户/)).toBeInTheDocument()
    expect(screen.getByText(/带电脑/)).toBeInTheDocument()
    expect(screen.getByText('返程')).toBeInTheDocument()
    // 附加块从文本补上（plan 里没有预算/天气）
    expect(screen.getByText(/合计：约 3000 元/)).toBeInTheDocument()
    expect(screen.getByText(/目的地天气提醒：北京 晴/)).toBeInTheDocument()
    // plan 模式不走文本解析（文本正文与 plan 不一致时以 plan 为准）
    expect(screen.queryByText('高铁 G999')).not.toBeInTheDocument()
  })

  it('预算块：文本回退模式单独成块展示', () => {
    render(<TripCard text={TRIP_TEXT + '\n\n💰 费用估算（参考价）：\n· 合计：约 5000 元'} />)
    expect(screen.getByText(/合计：约 5000 元/)).toBeInTheDocument()
  })

  it('尾部块：多行天气/应急/报销/政策依据不丢内容', () => {
    const text = [
      '📋 南京 2 天出差',
      '💡 安排理由：',
      '  · 按标准选住宿',
      '🚄 去程：高铁',
      '🏨 住宿：全季酒店',
      '🚄 返程：高铁',
      '📌 行程安排：',
      '  · 2026-08-20 抵达后入住酒店',
      '💰 预算参考（按公司差旅标准上限估算）：',
      '· 住宿：≤ 400 元/晚',
      '🌤️ 目的地天气提醒（出行天气，出发日：2026-08-20）：',
      '· 出发地：临沂 雷暴伴冰雹，降水概率 88%',
      '· 目的地：南京 雷暴伴冰雹，降水概率 100%',
      '⚠️ 异常天气安全提醒：',
      '台风、暴雨等极端天气处理步骤：提前关注天气预报',
      '💼 报销提醒：出差结束后 30 个自然日内提交报销',
      '📌 政策依据：01_travel_standards、02_reimbursement_policy',
    ].join('\n')
    render(<TripCard text={text} />)
    // 天气多行内容完整保留（标题行 + 两条 · 内容行）
    expect(screen.getByText(/出发地：临沂 雷暴伴冰雹/)).toBeInTheDocument()
    expect(screen.getByText(/目的地：南京 雷暴伴冰雹/)).toBeInTheDocument()
    // 尾部块（应急/报销/政策依据）完整保留
    expect(screen.getByText(/台风、暴雨等极端天气处理步骤/)).toBeInTheDocument()
    expect(screen.getByText(/出差结束后 30 个自然日内提交报销/)).toBeInTheDocument()
    expect(screen.getByText(/01_travel_standards、02_reimbursement_policy/)).toBeInTheDocument()
  })
})
