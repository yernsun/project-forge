export const themePreferences = ['system', 'light', 'dark'] as const
export type ThemePreference = (typeof themePreferences)[number]
export type ResolvedTheme = Exclude<ThemePreference, 'system'>

export const darkThemeClass = 'app-dark'

const themeStorageKey = 'app.theme'
const darkThemeQuery = '(prefers-color-scheme: dark)'

const isThemePreference = (value: string | null): value is ThemePreference =>
  themePreferences.includes(value as ThemePreference)

export function readThemePreference(): ThemePreference {
  const persisted = localStorage.getItem(themeStorageKey)
  return isThemePreference(persisted) ? persisted : 'system'
}

export function getThemeMediaQuery(): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(darkThemeQuery) : null
}

export function resolveTheme(
  preference: ThemePreference,
  mediaQuery: Pick<MediaQueryList, 'matches'> | null = getThemeMediaQuery(),
): ResolvedTheme {
  if (preference !== 'system') return preference
  return mediaQuery?.matches === true ? 'dark' : 'light'
}

export function applyTheme(
  preference: ThemePreference,
  mediaQuery: Pick<MediaQueryList, 'matches'> | null = getThemeMediaQuery(),
): ResolvedTheme {
  const resolved = resolveTheme(preference, mediaQuery)
  const root = document.documentElement
  root.classList.toggle(darkThemeClass, resolved === 'dark')
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
  return resolved
}

export function persistThemePreference(preference: ThemePreference): void {
  localStorage.setItem(themeStorageKey, preference)
}
