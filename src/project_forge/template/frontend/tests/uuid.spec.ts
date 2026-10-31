import { describe, expect, it, vi } from 'vitest'

import { createUuid, installRandomUuidCompatibility } from '@/shared/uuid'

const nativeUuid = '10000000-2000-4000-8000-300000000000' as const

function deterministicCrypto(): Crypto {
  return {
    getRandomValues: vi.fn((array: Uint8Array) => {
      array.set(Array.from({ length: 16 }, (_value, index) => index))
      return array
    }),
  } as unknown as Crypto
}

describe('UUID browser compatibility', () => {
  it('uses the native implementation when the secure context exposes it', () => {
    const randomUUID = vi.fn(() => nativeUuid)
    const getRandomValues = vi.fn()
    const cryptoApi = { getRandomValues, randomUUID } as unknown as Crypto

    expect(createUuid(cryptoApi)).toBe(nativeUuid)
    expect(randomUUID).toHaveBeenCalledOnce()
    expect(getRandomValues).not.toHaveBeenCalled()
  })

  it('creates an RFC 4122 version 4 UUID when LAN HTTP omits randomUUID', () => {
    const cryptoApi = deterministicCrypto()

    expect(createUuid(cryptoApi)).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
    expect(cryptoApi.getRandomValues).toHaveBeenCalledOnce()
  })

  it('installs an idempotent randomUUID compatibility method', () => {
    const cryptoApi = deterministicCrypto()

    installRandomUuidCompatibility(cryptoApi)
    const installed = cryptoApi.randomUUID
    installRandomUuidCompatibility(cryptoApi)

    expect(cryptoApi.randomUUID).toBe(installed)
    expect(cryptoApi.randomUUID()).toBe('00010203-0405-4607-8809-0a0b0c0d0e0f')
  })

  it('fails closed instead of using a weak random source', () => {
    const cryptoApi = {} as Crypto

    expect(() => createUuid(cryptoApi)).toThrow('cryptographically secure UUID source')
    expect(() => installRandomUuidCompatibility(cryptoApi)).toThrow(
      'cryptographically secure UUID source',
    )
    expect(() => createUuid(null)).toThrow('cryptographically secure UUID source')
  })
})
