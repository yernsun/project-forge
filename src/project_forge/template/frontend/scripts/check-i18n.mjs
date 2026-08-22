import { readFile } from 'node:fs/promises'

const root = new URL('../src/shared/i18n/locales/', import.meta.url)
const parse = async (name) => JSON.parse(await readFile(new URL(name, root), 'utf8'))
const flatten = (value, prefix = '') => Object.entries(value).flatMap(([key, child]) => {
  const path = prefix ? `${prefix}.${key}` : key
  return child && typeof child === 'object' && !Array.isArray(child) ? flatten(child, path) : [path]
})

const zh = new Set(flatten(await parse('zh-CN.json')))
const en = new Set(flatten(await parse('en-US.json')))
const missingZh = [...en].filter((key) => !zh.has(key))
const missingEn = [...zh].filter((key) => !en.has(key))
if (missingZh.length || missingEn.length) {
  console.error({ missingZh, missingEn })
  process.exitCode = 1
}
