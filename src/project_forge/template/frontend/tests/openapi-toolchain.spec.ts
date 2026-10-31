import { spawnSync } from 'node:child_process'
import { resolve } from 'node:path'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

import { expect, it } from 'vitest'

it('keeps Redocly URL header matching compatible with patched minimatch', () => {
  const result = spawnSync(process.execPath, [
    '--import', pathToFileURL(resolve('scripts/openapi-typescript-compat.mjs')).href,
    '--eval', `
      const assert = require('node:assert/strict')
      const { createRequire } = require('node:module')
      const generator = createRequire(require.resolve('openapi-typescript'))
      const core = createRequire(generator.resolve('@redocly/openapi-core'))
      const { readFileFromUrl } = core('./utils.js')
      assert.equal(typeof core('minimatch').Minimatch, 'function')
      readFileFromUrl('https://api.example.invalid/v1/schema.json', {
        headers: [
          { matches: 'api.example.invalid/**', name: 'X-Matched', value: 'yes' },
          { matches: 'other.example.invalid/**', name: 'X-Unrelated', value: 'no' },
        ],
        customFetch: async (_url, { headers }) => {
          assert.deepEqual(headers, { 'X-Matched': 'yes' })
          return new Response('{}', { headers: { 'content-type': 'application/json' } })
        },
      }).then(({ body }) => assert.equal(body, '{}'))
    `,
  ], { encoding: 'utf8' })

  expect(result.status, result.stderr || result.stdout).toBe(0)
})
