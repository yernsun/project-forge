import { defineStore } from 'pinia'
import type { usePrimeVue } from 'primevue/config'
import { ref } from 'vue'

import { i18n, initialLocale, primeLocales, type AppLocale } from '@/shared/i18n'

type PrimeVueApi = ReturnType<typeof usePrimeVue>

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<AppLocale>(initialLocale)

  function setLocale(next: AppLocale, primeVue: PrimeVueApi): void {
    locale.value = next
    i18n.global.locale.value = next
    document.documentElement.lang = next
    localStorage.setItem('app.locale', next)
    if (primeVue.config.locale) Object.assign(primeVue.config.locale, primeLocales[next])
  }

  return { locale, setLocale }
})
