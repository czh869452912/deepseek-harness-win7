import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
const { parseIndexBody } = await import(pathToFileURL(resolve(process.argv[2], 'packages/boot/plugin-market/src/parse.ts')).href)
const encoder = new TextEncoder()
const texts: string[] = JSON.parse(readFileSync(process.argv[3], 'utf8'))
console.log(JSON.stringify(texts.map(text => parseIndexBody(encoder.encode(text), 'https://market.example/index.json'))))
