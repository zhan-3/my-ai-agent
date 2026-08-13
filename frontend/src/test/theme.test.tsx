import { describe, expect, it, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import ThemeToggle from '@/components/ThemeToggle'
import { ThemeProvider, applyTheme, resolveTheme } from '@/lib/theme'

describe('resolveTheme / applyTheme（纯逻辑）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  it('三态 → 实际明暗：system 跟随系统偏好', () => {
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
  })

  it('applyTheme 切换 <html> 的 dark class', () => {
    applyTheme('light', false)
    expect(document.documentElement.classList.contains('dark')).toBe(false)
    applyTheme('dark', false)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    applyTheme('system', true)
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})

describe('ThemeToggle（三态循环 + 持久化）', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.classList.remove('dark')
  })

  function setup() {
    return render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    )
  }

  it('默认跟随系统（jsdom matchMedia matches=false → 浅色），点击三态循环', () => {
    setup()
    const btn = screen.getByTestId('theme-toggle')
    expect(btn).toHaveAccessibleName('主题：跟随系统，点击切换为浅色')

    fireEvent.click(btn) // → light
    expect(btn).toHaveAccessibleName('主题：浅色，点击切换为深色')
    expect(document.documentElement.classList.contains('dark')).toBe(false)

    fireEvent.click(btn) // → dark
    expect(btn).toHaveAccessibleName('主题：深色，点击切换为跟随系统')
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    fireEvent.click(btn) // → system（回起点）
    expect(btn).toHaveAccessibleName('主题：跟随系统，点击切换为浅色')
  })

  it('选择持久化到 localStorage（key: xw_theme）', () => {
    setup()
    fireEvent.click(screen.getByTestId('theme-toggle')) // light
    fireEvent.click(screen.getByTestId('theme-toggle')) // dark
    expect(localStorage.getItem('xw_theme')).toBe('dark')
  })

  it('重新挂载后恢复已存选择', () => {
    const { unmount } = setup()
    fireEvent.click(screen.getByTestId('theme-toggle')) // light
    fireEvent.click(screen.getByTestId('theme-toggle')) // dark
    unmount()

    setup() // 重新挂载 → 读取 localStorage
    expect(screen.getByTestId('theme-toggle')).toHaveAccessibleName(
      '主题：深色，点击切换为跟随系统',
    )
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})
