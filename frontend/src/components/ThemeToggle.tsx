import { Monitor, Moon, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useTheme, type ThemeMode } from '@/lib/theme'

// 深浅色切换：三态循环（浅色 → 深色 → 跟随系统），图标即当前状态

const NEXT: Record<ThemeMode, ThemeMode> = { light: 'dark', dark: 'system', system: 'light' }
const ICONS: Record<ThemeMode, typeof Sun> = { light: Sun, dark: Moon, system: Monitor }
const LABELS: Record<ThemeMode, string> = {
  light: '浅色',
  dark: '深色',
  system: '跟随系统',
}

export default function ThemeToggle() {
  const { mode, setMode } = useTheme()
  const Icon = ICONS[mode]
  const next = NEXT[mode]
  const label = LABELS[mode]
  return (
    <Button
      variant="ghost"
      size="icon"
      data-testid="theme-toggle"
      title={`主题：${label}（点击切换为${LABELS[next]}）`}
      aria-label={`主题：${label}，点击切换为${LABELS[next]}`}
      onClick={() => setMode(next)}
    >
      <Icon />
    </Button>
  )
}
