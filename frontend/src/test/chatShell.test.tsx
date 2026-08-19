import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import ChatShell from '@/components/ChatShell'
import { ThemeProvider } from '@/lib/theme'
import { SUGGESTIONS } from '@/lib/agents'
import * as chatApi from '@/api/chat'

vi.mock('@/api/chat', () => ({
  sendMessage: vi.fn(),
  streamChat: vi.fn(),
  parseSSEBuffer: vi.fn(() => ({ events: [], rest: '' })),
}))
vi.mock('@/api/memory', () => ({
  getMemory: vi.fn().mockResolvedValue({ preferences: [], itineraries: [] }),
  cancelTrip: vi.fn(),
  getMessages: vi.fn().mockResolvedValue({ messages: [] }),
}))
vi.mock('@/api/stats', () => ({
  getStats: vi.fn().mockResolvedValue({}),
}))

function wrapper({ children }: { children: React.ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>
}

// 快捷提问：点击只填入输入框（可确认/编辑后发送），不直接发送
describe('ChatShell 快捷提问', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染全部快捷提问按钮', () => {
    render(<ChatShell username="tester" onLogout={vi.fn()} />, { wrapper })
    for (const s of SUGGESTIONS) {
      expect(screen.getByRole('button', { name: s })).toBeInTheDocument()
    }
  })

  it('点击快捷提问：填入输入框 + 聚焦，但不发送', () => {
    render(<ChatShell username="tester" onLogout={vi.fn()} />, { wrapper })
    const first = SUGGESTIONS[0]
    const input = screen.getByPlaceholderText('输入差旅问题，回车发送…') as HTMLInputElement
    fireEvent.click(screen.getByRole('button', { name: first }))

    expect(input.value).toBe(first)
    expect(input).toHaveFocus()
    expect(chatApi.streamChat).not.toHaveBeenCalled()
    expect(chatApi.sendMessage).not.toHaveBeenCalled()
  })

  it('填入后仍可编辑再发送（输入框可修改）', () => {
    render(<ChatShell username="tester" onLogout={vi.fn()} />, { wrapper })
    const first = SUGGESTIONS[0]
    const input = screen.getByPlaceholderText('输入差旅问题，回车发送…') as HTMLInputElement
    fireEvent.click(screen.getByRole('button', { name: first }))
    fireEvent.change(input, { target: { value: first + '（修改）' } })
    expect(input.value).toBe(first + '（修改）')
  })
})
