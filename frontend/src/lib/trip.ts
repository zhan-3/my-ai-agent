// 行程答案解析（纯函数）：把后端「📋/💡/🚄/🏨/📌/💰/🌤️/📅」整体文本格式解析成结构化数据。
// 后端返回结构化 plan 后 TripCard 走 plan（planToParsed），本解析保留作文本回退兜底（历史回看/旧后端）。

export interface TripRow {
  label: string | null // '去程'|'住宿'|'返程'，匹配不到为 null
  text: string
}

export interface TripReminder {
  cls: 'wx' | 'dt'
  text: string
}

export interface ParsedTrip {
  summary: string
  reasons: string[]
  rows: TripRow[] // 整体字段行：去程 / 住宿 / 返程（不再逐日切块）
  diet: string // 🍽️ 饮食偏好（一次性提示，不逐日重复）
  itinerary: string[] // 📌 行程安排 的每日要点（每项「日期 内容」）
  budget: string // 💰 费用估算块（附加在行程正文之后）
  reminders: TripReminder[]
  tail: string // ⚠️应急/💼报销/📌政策依据/✅常驻城市等尾部块，原样保留不丢内容
}

// slice 1 结构化 plan：契约类型来自后端 OpenAPI（src/api/contract.ts，pnpm gen:api 生成）
import type { TripPlan } from '@/api/contract'

export type { TripPlan }

// 旧格式逐日块的行标签（历史回看兼容）
const OLD_ROW_RE = /^(交通|住宿|活动|用餐|备注)[：:]\s*(.*)$/

// 尾部块标记：这些块紧跟 💰/🌤️ 之后，逐块切分会把多行内容（如天气详情、应急步骤）切丢，
// 一律整体原样保留。
const TAIL_MARK = ['⚠️', '💼', '📌', '✅']
const isTailMark = (t: string) => TAIL_MARK.some((m) => t.startsWith(m))
// 任意块标题：结束上一块（预算续行 / 天气续行 / 旧格式逐日块）
const isBlockStart = (t: string) =>
  t.startsWith('📋') ||
  t.startsWith('💡') ||
  t.startsWith('💰') ||
  t.startsWith('🌤️') ||
  t.startsWith('📅') ||
  t.startsWith('🚄') ||
  t.startsWith('🏨') ||
  t.startsWith('📌') ||
  isTailMark(t) ||
  (t.startsWith('【') && t.endsWith('】'))

export function parseTrip(text: string): ParsedTrip {
  let summary = ''
  const reasons: string[] = []
  const rows: TripRow[] = []
  let diet = ''
  const itinerary: string[] = []
  let budget = ''
  const reminders: TripReminder[] = []
  let tail = ''
  let inReasons = false
  let inBudget = false // 💰 预算块是多行（头行 + 「·」续行），成块收集
  let inWeather = false // 🌤️ 天气块是多行（标题行 + 「·」内容行），并入同一条 reminder
  let inItinerary = false // 📌 行程安排 的「·」要点行
  let curDay: { date: string; rows: string[] } | null = null // 旧格式【】逐日块（历史回看兼容）

  const flushDay = () => {
    if (curDay && curDay.rows.length) {
      itinerary.push(`${curDay.date} ${curDay.rows.join('；')}`)
    }
    curDay = null
  }

  for (const raw of text.split('\n')) {
    const t = raw.trim()
    if (!t) {
      flushDay()
      continue
    }

    // 尾部块（应急/报销/政策依据/常驻城市）：已进入则原样收集到底
    if (tail) {
      tail += '\n' + t
      continue
    }
    // 天气块续行：标题行后的内容行并入最后一条 reminder，直到遇到下一个块标记
    if (inWeather) {
      if (isBlockStart(t)) {
        inWeather = false
        // 落入下面的正常分支继续处理（如 ⚠️ 应急块）
      } else {
        reminders[reminders.length - 1].text += '\n' + t
        continue
      }
    }
    if (t.startsWith('📋')) {
      inBudget = false
      summary = t.replace(/^📋\s*/, '')
      continue
    }
    if (t.startsWith('💡')) {
      inBudget = false
      inReasons = true
      const r = t.replace(/^💡\s*/, '')
      if (r !== '安排理由' && r !== '安排理由：') reasons.push(r)
      continue
    }
    if (t.startsWith('💰')) {
      inReasons = false
      inBudget = true
      budget = (budget ? budget + '\n' : '') + t
      continue
    }
    if (inBudget) {
      if (isBlockStart(t)) {
        inBudget = false
      } else {
        budget += '\n' + t
        continue
      }
    }
    if (t.startsWith('🚄')) {
      inReasons = false
      flushDay()
      const m = t.replace(/^🚄\s*/, '').match(/^(去程|返程)[：:]\s*(.*)$/)
      if (m) rows.push({ label: m[1], text: m[2] })
      continue
    }
    if (t.startsWith('🏨')) {
      inReasons = false
      flushDay()
      const m = t.replace(/^🏨\s*/, '').match(/^住宿[：:]\s*(.*)$/)
      if (m) rows.push({ label: '住宿', text: m[1] })
      continue
    }
    if (t.startsWith('🍽️')) {
      inReasons = false
      flushDay()
      diet = t
      continue
    }
    if (t.startsWith('📌')) {
      inReasons = false
      flushDay()
      inItinerary = true
      continue
    }
    // 旧格式逐日块（历史回看兼容）：折叠成一条 itinerary「日期 交通：..；住宿：..」
    if (t.startsWith('【') && t.endsWith('】')) {
      inReasons = false
      flushDay()
      curDay = { date: t.slice(1, -1), rows: [] }
      continue
    }
    if (t.startsWith('🌤️')) {
      flushDay()
      reminders.push({ cls: 'wx', text: t })
      inWeather = true
      continue
    }
    if (t.startsWith('📅')) {
      flushDay()
      reminders.push({ cls: 'dt', text: t })
      continue
    }
    if (isTailMark(t)) {
      flushDay()
      tail = t
      continue
    }
    if (inReasons) {
      reasons.push(t.replace(/^·\s*/, ''))
      continue
    }
    if (inItinerary && t.startsWith('·')) {
      itinerary.push(t.replace(/^·\s*/, ''))
      continue
    }
    if (curDay) {
      const m = t.match(OLD_ROW_RE)
      curDay.rows.push(m ? `${m[1]}：${m[2]}` : t)
    }
  }
  flushDay()
  return { summary, reasons, rows, diet, itinerary, budget, reminders, tail }
}

// 结构化 plan → 统一渲染形状（与 parseTrip 输出同构，整体结构不逐日切块）。
// budget/天气等附加块不在 plan 里，由调用方从文本解析补充（见 TripCard）。
export function planToParsed(plan: TripPlan): ParsedTrip {
  const days = plan.days ?? []
  const rows: TripRow[] = []
  const itinerary: string[] = []
  if (days.length) {
    const first = days[0]
    const last = days[days.length - 1]
    if (first.transport) rows.push({ label: '去程', text: first.transport })
    if (first.hotel && first.hotel !== '无（当晚返程）') rows.push({ label: '住宿', text: first.hotel })
    if (days.length > 1 && last.transport) rows.push({ label: '返程', text: last.transport })
    for (const d of days) {
      const items = d.activities.filter((a) => a)
      if (d.notes) items.push(d.notes)
      if (items.length) itinerary.push(`${d.date} ${items.join('；')}`)
    }
  }
  return {
    summary: plan.summary,
    reasons: plan.reasons ?? [],
    rows,
    diet: '',
    itinerary,
    budget: '',
    reminders: [],
    tail: '',
  }
}

// 行程答案判定：行程规划 + 含「📋」（整体结构必有 summary 前缀）；兼容旧格式「【」
export function isTripAnswer(intent: string, answer: string): boolean {
  return intent === '行程规划' && (answer.includes('📋') || answer.includes('【'))
}
