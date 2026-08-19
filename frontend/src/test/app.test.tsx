import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import App from '@/App'
import { ThemeProvider } from '@/lib/theme'
import * as authApi from '@/api/auth'

vi.mock('@/api/auth', () => ({ login: vi.fn(), register: vi.fn() }))
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
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

function wrapper({ children }: { children: React.ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>
}

// App 集成：无 token 显示登录页，登录成功后自动切换主界面（ChatShell）
describe('App 登录跳转', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('无 token：渲染登录面板', () => {
    render(<App />, { wrapper })
    expect(screen.getByText('欢迎使用晓问')).toBeInTheDocument()
    expect(screen.queryByText('多 Agent 智能出行助手')).not.toBeInTheDocument()
  })

  it('登录成功：自动切换主界面（无需手动刷新）', async () => {
    vi.mocked(authApi.login).mockResolvedValue({ token: 't', username: 'tester' })
    render(<App />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'tester' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'test123456' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(screen.getByText(/差旅出行助手/)).toBeInTheDocument()
    })
    // 登录页已离开
    expect(screen.queryByText('欢迎使用晓问')).not.toBeInTheDocument()
    // 欢迎语 + 左侧记忆栏出现
    expect(screen.getByText(/你好，我是晓问/)).toBeInTheDocument()
    expect(screen.getByText('🧠 Agent 记忆库')).toBeInTheDocument()
  })

  it('已登录（localStorage 有 token）：直接渲染主界面', () => {
    localStorage.setItem('xw_token', 't')
    localStorage.setItem('xw_user', 'tester')
    render(<App />, { wrapper })
    expect(screen.getByText(/差旅出行助手/)).toBeInTheDocument()
  })
})
