import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/hooks/useAuth'
import ThemeToggle from '@/components/ThemeToggle'

// 登录/注册面板：认证成功后回调 onAuthed（App 层切换主界面）
export default function AuthPanel({ onAuthed }: { onAuthed: (username: string) => void }) {
  const { authenticate } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(mode: 'login' | 'register') {
    const u = username.trim()
    if (!u || !password) {
      setError('用户名和密码不能为空')
      return
    }
    setError('')
    setBusy(true)
    try {
      const data = await authenticate(mode, u, password)
      onAuthed(data.username)
    } catch (e) {
      setError(e instanceof Error ? e.message : '失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex h-screen items-center justify-center bg-muted/30 p-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-xl">欢迎使用晓问</CardTitle>
          <CardDescription>登录后按账号隔离记忆（注册即登录）</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Input
            placeholder="用户名"
            value={username}
            autoComplete="username"
            aria-label="用户名"
            onChange={(e) => setUsername(e.target.value)}
          />
          <Input
            type="password"
            placeholder="密码"
            value={password}
            autoComplete="current-password"
            aria-label="密码"
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit('login')
            }}
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="grid grid-cols-2 gap-2">
            <Button disabled={busy} onClick={() => submit('login')}>
              登录
            </Button>
            <Button disabled={busy} variant="secondary" onClick={() => submit('register')}>
              注册
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
