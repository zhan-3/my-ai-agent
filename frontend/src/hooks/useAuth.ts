import { useCallback, useState } from 'react'
import { login as apiLogin, register as apiRegister, type AuthResult } from '@/api/auth'
import { TOKEN_KEY, USER_KEY } from '@/lib/storage'

// 认证状态：token/user 存 localStorage（与旧单文件互通），useState 镜像驱动界面
export function useAuth() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [username, setUsername] = useState<string | null>(() => localStorage.getItem(USER_KEY))

  const authenticate = useCallback(
    async (mode: 'login' | 'register', user: string, password: string): Promise<AuthResult> => {
      const fn = mode === 'login' ? apiLogin : apiRegister
      const data = await fn(user, password)
      localStorage.setItem(TOKEN_KEY, data.token)
      localStorage.setItem(USER_KEY, data.username)
      setToken(data.token)
      setUsername(data.username)
      return data
    },
    [],
  )

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setToken(null)
    setUsername(null)
  }, [])

  return { token, username, authenticate, logout }
}
