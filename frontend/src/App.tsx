import { useAuth } from '@/hooks/useAuth'
import AuthPanel from '@/components/AuthPanel'
import ChatShell from '@/components/ChatShell'

// 顶层：有 token → 主界面；无 token → 登录/注册
export default function App() {
  const { token, username, logout } = useAuth()
  if (!token) return <AuthPanel onAuthed={() => undefined} />
  return <ChatShell username={username} onLogout={logout} />
}
