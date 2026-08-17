import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useChat } from '@/hooks/useChat'
import * as chatApi from '@/api/chat'
import { ApiError } from '@/api/client'
import type { StreamEvent } from '@/api/chat'

vi.mock('@/api/chat', () => ({
  sendMessage: vi.fn(),
  streamChat: vi.fn(),
}))

const okPlan = {
  summary: '北京出差 4 天',
  reasons: ['按差旅标准选住宿'],
  date_is_vague: false,
  days: [
    { date: '2026-10-08', transport: '高铁 G1', hotel: '汉庭', activities: ['上午开会'], notes: '' },
  ],
}

const okResponse: chatApi.ChatResponse = {
  answer: '答',
  intent: '行程规划',
  reason: 'r',
  plan: okPlan,
  stats: null,
  history: null,
  sources: [],
}

/** 流式成功：模拟 SSE 阶段事件回调 + done 返回 */
function mockStreamOk() {
  vi.mocked(chatApi.streamChat).mockImplementation(
    async (_t: string, _token: string, onEvent: (e: StreamEvent) => void) => {
      onEvent({ type: 'stage', status: 'intent', intent: '行程规划' })
      onEvent({ type: 'stage', status: 'working', intent: '行程规划' })
      onEvent({ type: 'stage', status: 'done', intent: '行程规划' })
      return okResponse
    },
  )
}

describe('useChat SSE 发送流', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('流式发送：阶段事件回调 + done 消息上屏（含 plan）', async () => {
    mockStreamOk()
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    await act(async () => {
      await result.current.send('你好')
    })

    expect(chatApi.streamChat).toHaveBeenCalledTimes(1)
    expect(result.current.messages).toEqual([
      { role: 'user', text: '你好' },
      { role: 'ai', text: '答', intent: '行程规划', plan: okPlan, stats: null, history: null },
    ])
    expect(result.current.busy).toBe(false)
    expect(result.current.stages).toEqual([]) // done 后进度清空
  })

  it('同一可见对话复用 conversationId，新对话重置消息并更换 ID', async () => {
    mockStreamOk()
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))
    const firstId = result.current.conversationId

    await act(async () => {
      await result.current.send('你好')
    })
    expect(vi.mocked(chatApi.streamChat).mock.calls[0][3]).toBe(firstId)

    act(() => result.current.startNewConversation())
    expect(result.current.conversationId).not.toBe(firstId)
    expect(result.current.messages).toEqual([])
  })

  it('busy 期间防重复提交（同轮两次 send 只发一次）', async () => {
    let resolve!: (v: chatApi.ChatResponse) => void
    vi.mocked(chatApi.streamChat).mockImplementation(
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

    expect(chatApi.streamChat).toHaveBeenCalledTimes(1)
    expect(result.current.messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  it('401 触发登出且不追加错误消息', async () => {
    const onUnauthorized = vi.fn()
    vi.mocked(chatApi.streamChat).mockRejectedValue(new ApiError(401, '未登录'))
    const { result } = renderHook(() => useChat({ onUnauthorized }))

    await act(async () => {
      await result.current.send('hi')
    })

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(result.current.messages.some((m) => m.text.includes('⚠️'))).toBe(false)
    expect(chatApi.sendMessage).not.toHaveBeenCalled()
  })

  it('旧后端 404：回退 POST /api/chat', async () => {
    vi.mocked(chatApi.streamChat).mockRejectedValue(new ApiError(404, 'Not Found'))
    vi.mocked(chatApi.sendMessage).mockResolvedValue(okResponse)
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    await act(async () => {
      await result.current.send('你好')
    })

    expect(chatApi.sendMessage).toHaveBeenCalledTimes(1)
    expect(result.current.messages.at(-1)).toMatchObject({ role: 'ai', text: '答' })
  })

  it('网络错误追加降级文案', async () => {
    vi.mocked(chatApi.streamChat).mockRejectedValue(new Error('网络错误，请确认服务已启动'))
    const { result } = renderHook(() => useChat({ onUnauthorized: vi.fn() }))

    await act(async () => {
      await result.current.send('hi')
    })

    expect(result.current.messages.at(-1)).toEqual({
      role: 'ai',
      text: '⚠️ 网络错误，请确认后端已启动。',
      plan: null,
    })
  })
})
