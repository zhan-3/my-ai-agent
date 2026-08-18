import { describe, expect, it } from 'vitest'
import { parseSSEBuffer } from '@/api/chat'
import { ApiError } from '@/api/client'
import { applyStage } from '@/hooks/useChat'

describe('parseSSEBuffer：SSE 缓冲解析（跨 chunk 边界）', () => {
  it('单帧解析', () => {
    const { events, rest } = parseSSEBuffer('data: {"type":"stage","status":"start"}\n\n')
    expect(events).toEqual([{ type: 'stage', status: 'start' }])
    expect(rest).toBe('')
  })

  it('事件被切成两个 chunk：缓冲区续接完整解析', () => {
    // chunk1 只送来前半帧
    const first = parseSSEBuffer('data: {"type":"stage","status":"work')
    expect(first.events).toEqual([])
    expect(first.rest).toBe('data: {"type":"stage","status":"work')
    // chunk2 补全
    const second = parseSSEBuffer(first.rest + 'ing","intent":"行程规划"}\n\n')
    expect(second.events).toEqual([{ type: 'stage', status: 'working', intent: '行程规划' }])
  })

  it('一帧里多个事件', () => {
    const { events } = parseSSEBuffer(
      'data: {"type":"stage","status":"intent","intent":"行程规划"}\n\ndata: {"type":"stage","status":"working","intent":"行程规划"}\n\n',
    )
    expect(events).toHaveLength(2)
    expect(events[1]).toMatchObject({ type: 'stage', status: 'working' })
  })

  it('坏帧忽略，正常帧保留', () => {
    const { events } = parseSSEBuffer('data: not-json\n\ndata: {"type":"done","answer":"答"}\n\n')
    expect(events).toEqual([{ type: 'done', answer: '答' }])
  })
})

describe('ApiError：保留结构化服务故障', () => {
  it('保留 code 与 retryable', () => {
    const error = new ApiError(503, {
      message: '政策服务暂时不可用',
      code: 'policy_unavailable',
      retryable: true,
    })
    expect(error.message).toBe('政策服务暂时不可用')
    expect(error.code).toBe('policy_unavailable')
    expect(error.retryable).toBe(true)
  })
})

describe('applyStage：阶段事件 → 进度列表', () => {
  it('start 重置为理解中', () => {
    expect(applyStage([], { status: 'start' })).toEqual([{ intent: '__start__', status: 'working' }])
  })

  it('子 Agent 开始时替换主管决策占位', () => {
    const out = applyStage([{ intent: '__start__', status: 'working' }], {
      status: 'working',
      intent: '行程规划',
    })
    expect(out).toEqual([{ intent: '行程规划', status: 'working' }])
  })

  it('同一意图 working → done 去重更新', () => {
    let s = applyStage([], { status: 'start' })
    s = applyStage(s, { status: 'working', intent: '行程规划' })
    s = applyStage(s, { status: 'working', intent: '行程规划' }) // 重复 working 不叠加
    expect(s.filter((x) => x.intent === '行程规划')).toHaveLength(1)
    s = applyStage(s, { status: 'done', intent: '行程规划' })
    expect(s.find((x) => x.intent === '行程规划')?.status).toBe('done')
  })

  it('多个子 Agent 各自推进', () => {
    let s = applyStage([], { status: 'start' })
    s = applyStage(s, { status: 'working', intent: '行程规划' })
    s = applyStage(s, { status: 'working', intent: '偏好记录' })
    s = applyStage(s, { status: 'done', intent: '行程规划' })
    expect(s.map((x) => x.intent)).toEqual(['行程规划', '偏好记录'])
    expect(s.find((x) => x.intent === '行程规划')?.status).toBe('done')
    expect(s.find((x) => x.intent === '偏好记录')?.status).toBe('working')
  })
})
