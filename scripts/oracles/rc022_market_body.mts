import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const { parseIndexBody } = await import(pathToFileURL(resolve(process.argv[2], 'packages/boot/plugin-market/src/parse.ts')).href)
const raw = JSON.parse(readFileSync(process.argv[3], 'utf8')).map((value: string) =>
  parseIndexBody(new Uint8Array(Buffer.from(value, 'base64')), 'https://market.example/index.json'))
writeFileSync(resolve(dirname(process.argv[3]), 'source-diagnostics.json'), JSON.stringify(raw))
console.log(JSON.stringify(raw.map((result: any) => !result.ok && result.reason.startsWith('must be JSON: ')
  ? { ok: false, path: result.path, reasonPrefix: 'must be JSON: ', diagnosticPresent: result.reason.length > 14 } : result)))
