import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'

// 契约(REQ-6 明暗主题):
// - ThemeProvider / useTheme 位于 @/lib/theme(与 lib/auth、lib/current-project 同层)
// - theme: 'light' | 'dark',默认 'light';不做跟随系统自动切换
// - toggleTheme():切换主题,同步 html 根元素 .dark 类,并写入 localStorage
// - 持久化键 'zeichen.theme'(与 'zeichen.currentProjectId' 命名约定一致),值为 'light' | 'dark'
// - 二次加载时恢复所选主题;index.html 内联初始化脚本保证首帧无闪烁
import { ThemeProvider, useTheme } from '@/lib/theme'

const STORAGE_KEY = 'zeichen.theme'

function ThemeProbe() {
  const { theme, toggleTheme } = useTheme()
  return (
    <>
      <p data-testid="theme-probe">{theme}</p>
      <button type="button" onClick={toggleTheme}>
        toggle-theme
      </button>
    </>
  )
}

function renderTheme() {
  return render(
    <ThemeProvider>
      <ThemeProbe />
    </ThemeProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.classList.remove('dark')
})

describe('ThemeProvider 默认与切换', () => {
  it('默认浅色:html 无 .dark 类,useTheme 为 light', () => {
    renderTheme()
    expect(screen.getByTestId('theme-probe')).toHaveTextContent('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })

  it('toggle 后 html.classList 含 dark,再 toggle 移除', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    renderTheme()
    await user.click(screen.getByRole('button', { name: 'toggle-theme' }))
    expect(document.documentElement).toHaveClass('dark')
    expect(screen.getByTestId('theme-probe')).toHaveTextContent('dark')
    await user.click(screen.getByRole('button', { name: 'toggle-theme' }))
    expect(document.documentElement).not.toHaveClass('dark')
    expect(screen.getByTestId('theme-probe')).toHaveTextContent('light')
  })

  it('localStorage 读写:toggle 持久化所选主题', async () => {
    const user = (await import('@testing-library/user-event')).default.setup()
    renderTheme()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'toggle-theme' }))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark')
    await user.click(screen.getByRole('button', { name: 'toggle-theme' }))
    expect(localStorage.getItem(STORAGE_KEY)).toBe('light')
  })

  it('二次加载恢复所选主题:预置 dark 后挂载即含 .dark', () => {
    localStorage.setItem(STORAGE_KEY, 'dark')
    renderTheme()
    expect(document.documentElement).toHaveClass('dark')
    expect(screen.getByTestId('theme-probe')).toHaveTextContent('dark')
  })

  it('不做跟随系统:系统偏好 dark 时仍默认浅色', () => {
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      media: '(prefers-color-scheme: dark)',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }) as unknown as typeof window.matchMedia
    renderTheme()
    expect(screen.getByTestId('theme-probe')).toHaveTextContent('light')
    expect(document.documentElement).not.toHaveClass('dark')
  })
})

describe('首帧无闪烁', () => {
  it('index.html 在 <head> 内联主题初始化脚本:读取持久化键并应用 dark 类', () => {
    const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf-8')
    const head = html.slice(0, html.indexOf('</head>'))
    const inlineScripts = [...head.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)].map(
      (m) => m[1],
    )
    expect(inlineScripts.length).toBeGreaterThan(0)
    const script = inlineScripts.join('\n')
    expect(script).toContain(STORAGE_KEY)
    expect(script).toContain('dark')
  })

  it('应用根部挂载 ThemeProvider:main.tsx 接入', () => {
    const main = readFileSync(new URL('../main.tsx', import.meta.url), 'utf-8')
    expect(main).toContain('ThemeProvider')
  })
})
