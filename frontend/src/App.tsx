import { useAuth } from '@/hooks/useAuth'
import AuthPanel from '@/components/AuthPanel'
import ChatShell from '@/components/ChatShell'

// 顶层：有 token → 主界面；无 token → 登录/注册
// App 持有唯一 useAuth 实例，authenticate 经 props 传给 AuthPanel，
// 登录成功后 token state 变化驱动本组件重渲染切换到主界面（无需刷新页面）
export default function App() {
  const { token, username, logout, authenticate } = useAuth()
  if (!token) return <AuthPanel authenticate={authenticate} />
  return <ChatShell username={username} onLogout={logout} />
}
