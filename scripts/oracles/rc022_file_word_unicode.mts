/** Freeze Unicode 16 file-id token boundaries used by pinned RequestFiles. */
import fs from 'node:fs'
import crypto from 'node:crypto'
import path from 'node:path'
if(process.versions.unicode!=='16.0')throw new Error('Unicode 16 required')
const file=path.join(process.argv[2]!,'packages/llm/llm-deepseek/src/request-files.ts'),ranges:number[][]=[]
for(let cp=0;cp<=0x10ffff;cp++){
 if(!/[\p{L}\p{N}_-]/u.test(String.fromCodePoint(cp)))continue
 const last=ranges.at(-1)
 if(last&&last[1]===cp-1)last[1]=cp
 else ranges.push([cp,cp])
}
fs.writeFileSync(process.argv[3]!,JSON.stringify({unicode:process.versions.unicode,node:process.version,
 source:'packages/llm/llm-deepseek/src/request-files.ts',sourceSha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex'),
 generator:'scripts/oracles/rc022_file_word_unicode.mts',ranges})+'\n')
