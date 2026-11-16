/** Freeze Node's Unicode 16 binary properties used by the pinned listing decoder. */
import fs from 'node:fs'
import crypto from 'node:crypto'
import path from 'node:path'
if (process.versions.unicode !== '16.0') throw new Error('Unicode 16 runtime required')
const source = process.argv[2]!, output = process.argv[3]!
const listing = path.join(source, 'packages/llm/llm-deepseek/src/listing.ts')
const rules = {
  unreadable: /[\p{Cc}\p{Zl}\p{Zp}\p{Bidi_Control}]/u,
  invisible: /[\p{White_Space}\p{Default_Ignorable_Code_Point}]/u,
}
const tables = Object.fromEntries(Object.entries(rules).map(([key, rule]) => {
  const ranges: number[][] = []
  for (let cp = 0; cp <= 0x10ffff; cp++) {
    if (!rule.test(String.fromCodePoint(cp))) continue
    const last = ranges.at(-1)
    if (last && last[1] === cp - 1) last[1] = cp
    else ranges.push([cp, cp])
  }
  return [key, ranges]
}))
fs.writeFileSync(output, JSON.stringify({ unicode: process.versions.unicode, node: process.version,
  source: 'packages/llm/llm-deepseek/src/listing.ts', sourceSha256: crypto.createHash('sha256').update(fs.readFileSync(listing)).digest('hex'),
  generator: 'scripts/oracles/rc022_badge_unicode.mts', tables }) + '\n')
