import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  applyTheme,
  getThemeMediaQuery,
  persistThemePreference,
  readThemePreference,
  type ResolvedTheme,
  type ThemePreference,
} from '@/shared/theme'

export const useThemeStore = defineStore('theme', () => {
  const mediaQuery = getThemeMediaQuery()
  const preference = ref<ThemePreference>(readThemePreference())
  const resolvedTheme = ref<ResolvedTheme>(applyTheme(preference.value, mediaQuery))
  let started = false

  function synchronize(): void {
    resolvedTheme.value = applyTheme(preference.value, mediaQuery)
  }

  function handleSystemThemeChange(): void {
    if (preference.value === 'system') synchronize()
  }

  function start(): void {
    if (started) return
    started = true
    mediaQuery?.addEventListener('change', handleSystemThemeChange)
    synchronize()
  }

  function stop(): void {
    if (!started) return
    started = false
    mediaQuery?.removeEventListener('change', handleSystemThemeChange)
  }

  function setTheme(next: ThemePreference): void {
    preference.value = next
    persistThemePreference(next)
    synchronize()
  }

  return { preference, resolvedTheme, setTheme, start, stop }
})
