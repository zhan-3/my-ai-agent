// 行程答案解析（纯函数）：把后端「📋/💡/【】/🌤️/📅」文本格式解析成结构化数据。
// slice 1 后端返回结构化 plan 后，TripCard 改走 plan，本解析保留作回退兜底。
// 来源：旧单文件 index.html renderTripCard 的解析逻辑，原样迁移（行为不变）。

export interface TripDayRow {
  label: string | null // '交通'|'住宿'|'活动'|'用餐'|'备注'，匹配不到为 null
  text: string
}

export interface TripDay {
  date: string
  rows: TripDayRow[]
}

export interface TripReminder {
  cls: 'wx' | 'dt'
  text: string
}

export interface ParsedTrip {
  summary: string
  reasons: string[]
  days: TripDay[]
  reminders: TripReminder[]
}

const ROW_RE = /^(交通|住宿|活动|用餐|备注)[：:]\s*(.*)$/

export function parseTrip(text: string): ParsedTrip {
  let summary = ''
  const reasons: string[] = []
  const days: TripDay[] = []
  const reminders: TripReminder[] = []
  let cur: TripDay | null = null
  let inReasons = false

  for (const raw of text.split('\n')) {
    const t = raw.trim()
    if (!t) continue
    if (t.startsWith('📋')) {
      summary = t.replace(/^📋\s*/, '')
      continue
    }
    if (t.startsWith('💡')) {
      inReasons = true
      // 标题行（如「安排理由：」）不入列表，避免与卡片标题重复（旧单文件原样照抄时的小瑕疵，此处修正）
      const r = t.replace(/^💡\s*/, '')
      if (r !== '安排理由' && r !== '安排理由：') reasons.push(r)
      continue
    }
    if (t.startsWith('【') && t.endsWith('】')) {
      inReasons = false
      cur = { date: t.slice(1, -1), rows: [] }
      days.push(cur)
      continue
    }
    if (t.startsWith('🌤️')) {
      reminders.push({ cls: 'wx', text: t })
      continue
    }
    if (t.startsWith('📅')) {
      reminders.push({ cls: 'dt', text: t })
      continue
    }
    if (inReasons) {
      reasons.push(t.replace(/^·\s*/, ''))
      continue
    }
    if (cur) {
      const m = t.match(ROW_RE)
      cur.rows.push(m ? { label: m[1], text: m[2] } : { label: null, text: t })
    }
  }
  return { summary, reasons, days, reminders }
}

// 与旧代码 `isTrip = intent === "行程规划" && answer.includes("【")` 一致
export function isTripAnswer(intent: string, answer: string): boolean {
  return intent === '行程规划' && answer.includes('【')
}
