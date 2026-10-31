export type Uuid = `${string}-${string}-${string}-${string}-${string}`

type RuntimeCrypto = Pick<Crypto, 'getRandomValues'> & {
  randomUUID?: () => Uuid
}

const unavailableMessage =
  'This browser does not provide a cryptographically secure UUID source. Use HTTPS or a modern browser.'

function version4Uuid(cryptoApi: RuntimeCrypto): Uuid {
  if (typeof cryptoApi.getRandomValues !== 'function') {
    throw new Error(unavailableMessage)
  }

  const bytes = cryptoApi.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export function createUuid(
  cryptoApi: RuntimeCrypto | null | undefined = globalThis.crypto,
): Uuid {
  if (!cryptoApi) throw new Error(unavailableMessage)

  const nativeRandomUuid = cryptoApi.randomUUID
  if (typeof nativeRandomUuid === 'function') {
    return nativeRandomUuid.call(cryptoApi)
  }
  return version4Uuid(cryptoApi)
}

export function installRandomUuidCompatibility(
  cryptoApi: RuntimeCrypto | null | undefined = globalThis.crypto,
): void {
  if (!cryptoApi) throw new Error(unavailableMessage)
  if (typeof cryptoApi.randomUUID === 'function') return
  if (typeof cryptoApi.getRandomValues !== 'function') {
    throw new Error(unavailableMessage)
  }

  Object.defineProperty(cryptoApi, 'randomUUID', {
    configurable: true,
    value: () => version4Uuid(cryptoApi),
  })
}
