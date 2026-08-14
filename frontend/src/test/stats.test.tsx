import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import StatsPanel from '@/components/StatsPanel'

// 差旅画像面板：拉 /api/stats 渲染确定性聚合（次数/天数/城市/年度），零 LLM
describe('StatsPanel', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.stubGlobal('fetch', vi.fn())
  })

  it('无数据时显示占位文案', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        has_data: false,
        trips: 0,
        total_days: 0,
        avg_days: 0,
        skipped_days: 0,
        top_cities: [],
        years: [],
      }),
    } as Response)

    render(<StatsPanel refreshKey={0} />)
    expect(await screen.findByText('暂无行程记录，规划后自动统计')).toBeInTheDocument()
  })

  it('有数据时渲染聚合卡片', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        has_data: true,
        trips: 3,
        total_days: 6,
        avg_days: 2,
        skipped_days: 0,
        top_cities: [
          { city: '北京', count: 2 },
          { city: '上海', count: 1 },
        ],
        years: [
          { year: '2025', count: 1 },
          { year: '2026', count: 2 },
        ],
      }),
    } as Response)

    render(<StatsPanel refreshKey={0} />)
    const totals = await screen.findAllByText((_, el) =>
      el?.textContent?.includes('累计出差 6 天 · 平均每次 2 天') ?? false,
    )
    expect(totals.length).toBeGreaterThan(0)
    expect(screen.getByText('北京 ×2')).toBeInTheDocument()
    expect(screen.getByText('上海 ×1')).toBeInTheDocument()
    expect(screen.getByText('2026 年 2 次')).toBeInTheDocument()
  })

  it('缺天数的旧记录给出诚实标注', async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        has_data: true,
        trips: 2,
        total_days: 3,
        avg_days: 1.5,
        skipped_days: 1,
        top_cities: [{ city: '北京', count: 2 }],
        years: [{ year: '2026', count: 2 }],
      }),
    } as Response)

    render(<StatsPanel refreshKey={0} />)
    expect(await screen.findByText('1 条旧记录缺天数，未计入天数统计')).toBeInTheDocument()
  })
})
