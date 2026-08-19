import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import AuthPanel from '@/components/AuthPanel'
import { ThemeProvider } from '@/lib/theme'
import { ApiError } from '@/api/client'
import * as sonner from 'sonner'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

// AuthPanel 内含 ThemeToggle（需要 ThemeProvider）
function wrapper({ children }: { children: React.ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>
}

// authenticate 由 App 传入（App 持有唯一 useAuth 实例）；AuthPanel 只负责调用 + 提示
describe('AuthPanel 登录/注册', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('空用户名/密码：本地校验提示，不调用 authenticate', async () => {
    const authenticate = vi.fn()
    render(<AuthPanel authenticate={authenticate} />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByText('用户名和密码不能为空')).toBeInTheDocument()
    expect(authenticate).not.toHaveBeenCalled()
  })

  it('401：显示后端错误文案（用户名或密码错误）', async () => {
    const authenticate = vi.fn().mockRejectedValue(new ApiError(401, '用户名或密码错误'))
    render(<AuthPanel authenticate={authenticate} />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'zhang' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
    expect(sonner.toast.error).toHaveBeenCalledWith('用户名或密码错误')
  })

  it('登录成功：toast 欢迎 + 传入的 authenticate 被调用（主界面切换由 App 的 token state 驱动）', async () => {
    const authenticate = vi.fn().mockResolvedValue({ token: 't', username: 'lily' })
    render(<AuthPanel authenticate={authenticate} />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'lily' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pass123' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => expect(sonner.toast.success).toHaveBeenCalledWith('欢迎回来，lily'))
    expect(authenticate).toHaveBeenCalledWith('login', 'lily', 'pass123')
  })

  it('注册成功：toast 提示 + 传入的 authenticate 被调用（mode=register）', async () => {
    const authenticate = vi.fn().mockResolvedValue({ token: 't', username: 'zhang' })
    render(<AuthPanel authenticate={authenticate} />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'zhang' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pass123' } })
    fireEvent.click(screen.getByRole('button', { name: '注册' }))

    await waitFor(() => expect(sonner.toast.success).toHaveBeenCalledWith('注册成功，已自动登录：zhang'))
    expect(authenticate).toHaveBeenCalledWith('register', 'zhang', 'pass123')
  })
})
