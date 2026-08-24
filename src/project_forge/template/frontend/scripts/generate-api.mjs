import { spawnSync } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const selectionPath = resolve(frontend, '.api-contract.json')
const selection = JSON.parse(await readFile(selectionPath, 'utf8'))
const sourceIndex = process.argv.indexOf('--source')
if (sourceIndex >= 0 && !process.argv[sourceIndex + 1]) {
  throw new Error('--source requires an OpenAPI JSON path')
}
const source = sourceIndex >= 0
  ? resolve(process.argv[sourceIndex + 1])
  : resolve(frontend, selection.source)
const target = resolve(frontend, 'src/shared/api/schema.d.ts')
const check = process.argv.includes('--check')
const temporary = check ? await mkdtemp(resolve(tmpdir(), 'project-forge-api-')) : null
const output = temporary ? resolve(temporary, 'schema.d.ts') : target
const executable = resolve(frontend, 'node_modules/openapi-typescript/bin/cli.js')

try {
  const result = spawnSync(process.execPath, [executable, source, '--output', output], {
    cwd: frontend,
    encoding: 'utf8',
  })
  if (result.status !== 0) {
    process.stderr.write(result.stderr || result.stdout)
    process.exitCode = result.status ?? 1
  } else if (check) {
    const [expected, actual] = await Promise.all([readFile(target), readFile(output)])
    if (!expected.equals(actual)) {
      console.error(`API types are stale for ${source}; run npm run api:generate or refresh the selected contract`)
      process.exitCode = 1
    } else {
      console.log(`API types match contract variant ${selection.variant}`)
    }
  }
} finally {
  if (temporary) await rm(temporary, { recursive: true, force: true })
}
