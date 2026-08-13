import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// 深浅色主题：三态（浅色 / 深色 / 跟随系统），localStorage 持久化（key: xw_theme）
// 首帧应用由 index.html 内联脚本完成（防闪烁）；本模块负责运行期切换与系统偏好监听

export type ThemeMode = 'light' | 'dark' | 'system'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_KEY = 'xw_theme'
export const DARK_QUERY = '(prefers-color-scheme: dark)'
export const THEME_OPTIONS: ThemeMode[] = ['light', 'dark', 'system']

/** 纯函数：三态模式 + 系统偏好 → 实际明暗（可单测） */
export function resolveTheme(mode: ThemeMode, systemDark: boolean): ResolvedTheme {
  return mode === 'system' ? (systemDark ? 'dark' : 'light') : mode
}

/** 应用主题：切换 <html> 上的 dark class */
export function applyTheme(mode: ThemeMode, systemDark: boolean): void {
  document.documentElement.classList.toggle('dark', resolveTheme(mode, systemDark) === 'dark')
}

export function readStoredTheme(): ThemeMode {
  const v = localStorage.getItem(THEME_KEY)
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
}

interface ThemeContextValue {
  mode: ThemeMode
  resolved: ResolvedTheme
  setMode: (m: ThemeMode) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<ThemeMode>(readStoredTheme)
  const [systemDark, setSystemDark] = useState<boolean>(() =>
    window.matchMedia(DARK_QUERY).matches,
  )

  // 跟随系统：监听系统偏好变化
  useEffect(() => {
    const mq = window.matchMedia(DARK_QUERY)
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 模式或系统偏好变化 → 应用 + 持久化
  useEffect(() => {
    applyTheme(mode, systemDark)
    localStorage.setItem(THEME_KEY, mode)
  }, [mode, systemDark])

  const setMode = useCallback((m: ThemeMode) => setModeState(m), [])
  const resolved = resolveTheme(mode, systemDark)
  const value = useMemo(() => ({ mode, resolved, setMode }), [mode, resolved, setMode])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme 必须在 ThemeProvider 内使用')
  return ctx
}
