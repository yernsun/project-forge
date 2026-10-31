import { createRequire } from 'node:module'

// openapi-typescript 7 requires Redocly 1, whose CommonJS caller expects a
// callable minimatch export. Keep patched minimatch 11 and adapt only this CLI
// process; preserve its named exports and leave installed package files intact.
// Remove with the upstream migration: openapi-ts/openapi-typescript#2644.
const compatibilityRequire = createRequire(import.meta.url)
const generatorRequire = createRequire(compatibilityRequire.resolve('openapi-typescript'))
const coreRequire = createRequire(generatorRequire.resolve('@redocly/openapi-core'))
const modulePath = coreRequire.resolve('minimatch')
const matching = coreRequire(modulePath)

if (typeof matching !== 'function') {
  if (typeof matching.minimatch !== 'function') {
    throw new TypeError('Unsupported minimatch API in the OpenAPI toolchain')
  }
  coreRequire.cache[modulePath].exports = Object.assign(matching.minimatch, matching)
}
