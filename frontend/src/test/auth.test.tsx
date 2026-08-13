import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import AuthPanel from '@/components/AuthPanel'
import { ThemeProvider } from '@/lib/theme'
import * as authApi from '@/api/auth'
import { ApiError } from '@/api/client'

vi.mock('@/api/auth', () => ({ login: vi.fn(), register: vi.fn() }))

// AuthPanel 内含 ThemeToggle（需要 ThemeProvider）
function wrapper({ children }: { children: React.ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>
}

describe('AuthPanel 登录/注册', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('空用户名/密码：本地校验提示，不发请求', async () => {
    render(<AuthPanel onAuthed={vi.fn()} />, { wrapper })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))
    expect(await screen.findByText('用户名和密码不能为空')).toBeInTheDocument()
    expect(authApi.login).not.toHaveBeenCalled()
  })

  it('401：显示后端错误文案（用户名或密码错误）', async () => {
    vi.mocked(authApi.login).mockRejectedValue(new ApiError(401, '用户名或密码错误'))
    render(<AuthPanel onAuthed={vi.fn()} />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'zhang' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名或密码错误')).toBeInTheDocument()
  })

  it('注册成功：回调 onAuthed（进入主界面）', async () => {
    vi.mocked(authApi.register).mockResolvedValue({ token: 't', username: 'zhang' })
    const onAuthed = vi.fn()
    render(<AuthPanel onAuthed={onAuthed} />, { wrapper })
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'zhang' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'pass123' } })
    fireEvent.click(screen.getByRole('button', { name: '注册' }))

    await screen.findByRole('button', { name: '注册' })
    expect(onAuthed).toHaveBeenCalledWith('zhang')
    expect(localStorage.getItem('xw_token')).toBe('t')
  })
})
