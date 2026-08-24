import { config } from '@vue/test-utils'
import { afterEach, vi } from 'vitest'

config.global.stubs = { transition: false }

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
