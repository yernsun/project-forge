import enUS from '@/shared/i18n/locales/en-US.json'
import zhCN from '@/shared/i18n/locales/zh-CN.json'
import { describe, expect, it } from 'vitest'

function keys(value: object, prefix = ''): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof child === 'object' && child !== null ? keys(child, path) : [path]
  })
}

describe('locale catalogs', () => {
  it('have identical key sets', () => {
    expect(keys(zhCN).sort()).toEqual(keys(enUS).sort())
  })
})
