import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useChat } from '@/hooks/useChat'
import * as chatApi from '@/api/chat'
import { ApiError } from '@/api/client'

vi.mock('@/api/chat', () => ({ sendMessage: vi.fn() }))

const okResponse: chatApi.ChatResponse = { answer: '答', intent: '其他', reason: 'r' }

describe('useChat 发送流', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('发送后用户消息与 AI 回复上屏', async () => {
    vi.mocked(chatApi.sendMessage).mockResolvedValue(okResponse)
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    await act(async () => {
      await result.current.send('你好')
    })

    expect(result.current.messages).toEqual([
      { role: 'user', text: '你好' },
      { role: 'ai', text: '答', intent: '其他' },
    ])
    expect(result.current.busy).toBe(false)
  })

  it('busy 期间防重复提交（同轮两次 send 只发一次）', async () => {
    let resolve!: (v: chatApi.ChatResponse) => void
    vi.mocked(chatApi.sendMessage).mockImplementation(
      () => new Promise((r) => (resolve = r)),
    )
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    let p1: Promise<unknown>
    let p2: Promise<unknown>
    act(() => {
      p1 = result.current.send('一')
      p2 = result.current.send('二') // 应被 busy 拦下
    })
    await act(async () => {
      resolve(okResponse)
      await p1
      await p2
    })

    expect(chatApi.sendMessage).toHaveBeenCalledTimes(1)
    expect(result.current.messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  it('401 触发登出且不追加错误消息', async () => {
    const onUnauthorized = vi.fn()
    vi.mocked(chatApi.sendMessage).mockRejectedValue(new ApiError(401, '未登录'))
    const { result } = renderHook(() => useChat({ onUnauthorized }))

    await act(async () => {
      await result.current.send('hi')
    })

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(result.current.messages.some((m) => m.text.includes('⚠️'))).toBe(false)
  })

  it('网络错误追加降级文案', async () => {
    vi.mocked(chatApi.sendMessage).mockRejectedValue(new Error('网络错误，请确认服务已启动'))
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    await act(async () => {
      await result.current.send('hi')
    })

    expect(result.current.messages.at(-1)).toEqual({
      role: 'ai',
      text: '⚠️ 网络错误，请确认后端已启动。',
    })
  })
})
