import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { darkThemeClass } from '@/shared/theme'
import { useThemeStore } from '@/shared/stores/theme'

function mockSystemTheme(initialMatches: boolean) {
  let matches = initialMatches
  let listener: ((event: MediaQueryListEvent) => void) | undefined
  const mediaQuery = {
    get matches() {
      return matches
    },
    media: '(prefers-color-scheme: dark)',
    addEventListener: vi.fn(
      (_type: string, next: (event: MediaQueryListEvent) => void) => {
        listener = next
      },
    ),
    removeEventListener: vi.fn(
      (_type: string, next: (event: MediaQueryListEvent) => void) => {
        if (listener === next) listener = undefined
      },
    ),
  } as unknown as MediaQueryList
  vi.stubGlobal('matchMedia', vi.fn(() => mediaQuery))

  return {
    mediaQuery,
    setMatches(next: boolean) {
      matches = next
      listener?.({ matches: next, media: mediaQuery.media } as MediaQueryListEvent)
    },
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  document.documentElement.classList.remove(darkThemeClass)
  delete document.documentElement.dataset.theme
  document.documentElement.style.removeProperty('color-scheme')
})

describe('theme preference', () => {
  it('persists explicit choices and follows operating-system changes in system mode', () => {
    const systemTheme = mockSystemTheme(false)
    const store = useThemeStore()
    store.start()

    expect(store.preference).toBe('system')
    expect(store.resolvedTheme).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')

    systemTheme.setMatches(true)
    expect(store.resolvedTheme).toBe('dark')
    expect(document.documentElement.classList.contains(darkThemeClass)).toBe(true)

    store.setTheme('light')
    expect(localStorage.getItem('app.theme')).toBe('light')
    systemTheme.setMatches(true)
    expect(store.resolvedTheme).toBe('light')
    expect(document.documentElement.classList.contains(darkThemeClass)).toBe(false)

    store.setTheme('dark')
    expect(localStorage.getItem('app.theme')).toBe('dark')
    expect(document.documentElement.style.colorScheme).toBe('dark')

    store.stop()
    expect(systemTheme.mediaQuery.removeEventListener).toHaveBeenCalledOnce()
  })

  it('falls back to system mode for an unknown persisted value', () => {
    localStorage.setItem('app.theme', 'unsupported')
    mockSystemTheme(false)

    expect(useThemeStore().preference).toBe('system')
  })
})
