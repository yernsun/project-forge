import { readFile, readdir } from 'node:fs/promises'
import { extname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = resolve(fileURLToPath(new URL('..', import.meta.url)))
const localeRoot = join(frontend, 'src/shared/i18n/locales')

const parse = async (name) => JSON.parse(await readFile(join(localeRoot, name), 'utf8'))
const flatten = (value, prefix = '', result = new Map()) => {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (child && typeof child === 'object' && !Array.isArray(child)) flatten(child, path, result)
    else result.set(path, child)
  }
  return result
}
const placeholders = (value) =>
  [...String(value).matchAll(/\{([^{}]+)\}/g)].map((match) => match[1]).sort()

async function sourceFiles(directory) {
  const result = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) result.push(...await sourceFiles(path))
    else if (['.ts', '.vue'].includes(extname(entry.name))) result.push(path)
  }
  return result
}

const zh = flatten(await parse('zh-CN.json'))
const en = flatten(await parse('en-US.json'))
const missingZh = [...en.keys()].filter((key) => !zh.has(key))
const missingEn = [...zh.keys()].filter((key) => !en.has(key))
const shapeErrors = [...en.keys()].flatMap((key) => {
  if (!zh.has(key)) return []
  const errors = []
  if (typeof en.get(key) !== typeof zh.get(key)) errors.push(`${key}: value types differ`)
  if (String(en.get(key)).trim() === '' || String(zh.get(key)).trim() === '') errors.push(`${key}: empty translation`)
  if (JSON.stringify(placeholders(en.get(key))) !== JSON.stringify(placeholders(zh.get(key)))) {
    errors.push(`${key}: interpolation placeholders differ`)
  }
  return errors
})

const used = new Set()
const literalCall = /\b(?:t|\$t)\(\s*(['"`])([^'"`]+)\1/g
for (const path of await sourceFiles(join(frontend, 'src'))) {
  const source = await readFile(path, 'utf8')
  for (const match of source.matchAll(literalCall)) {
    if (!match[2].includes('${')) used.add(match[2])
  }
}
const missingUsed = [...used].filter((key) => !en.has(key) || !zh.has(key))

if (missingZh.length || missingEn.length || shapeErrors.length || missingUsed.length) {
  console.error({ missingZh, missingEn, shapeErrors, missingUsed })
  process.exitCode = 1
} else {
  console.log(`i18n catalogs match; ${used.size} statically referenced keys verified`)
}
