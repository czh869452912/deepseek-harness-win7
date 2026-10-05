import {createHash} from 'node:crypto'
import {mkdir, writeFile, readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {compressZstdFrame, decompressZstdFrame, decompressZstdPrefix, scanZstdFrames} from '../../reference/packages/session/session-persistence-jsonl/src/zstd.ts'

if (process.versions.node !== '22.22.2') throw new Error('Pinned Node differs')
const directory = process.argv[2]
const phase = process.argv[3]
if (phase === 'produce') await mkdir(directory)
const sha = value => createHash('sha256').update(value).digest('hex')
function noise(length) {
  let state = 0x12345678
  const buffer = Buffer.alloc(length)
  for (let index = 0; index < length; index++) {
    state ^= state << 13
    state ^= state >>> 17
    state ^= state << 5
    buffer[index] = state & 255
  }
  return buffer
}
function observed(operation) {
  try { return {value:operation()} } catch(error) { return {error:error.message} }
}
const rows = []
if (phase === 'consume') {
  for (let index = 0; index < 10; index++) {
    const frame = await readFile(join(directory, `native-frame-${index}.bin`))
    rows.push({id:`cross-frame/${index}`,decoded:sha(await decompressZstdFrame(frame)),scan:scanZstdFrames(frame)})
  }
  await writeFile(join(directory,'source-consume.json'), JSON.stringify({node:process.versions.node,rows})+'\n')
} else {
const inputs = [Buffer.alloc(0), Buffer.from('abc'), Buffer.from('中文😀\n'),
  ...[127, 65535, 65536, 65537, 1048576, 1048607].map(length => Buffer.alloc(length, 65)),
  noise(190000)]
for (const [index, plaintext] of inputs.entries()) {
  const frame = await compressZstdFrame(plaintext)
  await writeFile(join(directory, `plain-${index}.bin`), plaintext)
  await writeFile(join(directory, `frame-${index}.bin`), frame)
  rows.push({id:`frame/${index}`, encoded:sha(frame), decoded:sha(await decompressZstdFrame(frame)), scan:scanZstdFrames(frame)})
  const cuts = [...new Set(frame.length <= 300 ? Array.from({length:frame.length}, (_, offset) => offset) :
    [...Array.from({length:21}, (_, offset) => offset), ...[0.1, 0.3, 0.5, 0.75].map(ratio => Math.floor(frame.length * ratio)),
      ...Array.from({length:8}, (_, offset) => frame.length - offset - 1)])].sort((left, right) => left - right)
  for (const cut of cuts) {
    let prefix
    try { prefix = {sha256:sha(await decompressZstdPrefix(frame.subarray(0, cut)))} }
    catch(error) { prefix = {error:error.code} }
    rows.push({id:`cut/${index}/${cut}`, scan:observed(() => scanZstdFrames(frame.subarray(0, cut))), prefix})
  }
  const damaged = Buffer.from(frame)
  damaged[damaged.length - 1] ^= 1
  let failure
  try { await decompressZstdFrame(damaged); failure = null } catch(error) { failure = error.code }
  rows.push({id:`checksum/${index}`, failure})
}
const magic = Buffer.from([0x28,0xb5,0x2f,0xfd])
for (let descriptor = 0; descriptor < 256; descriptor++) {
  const bytes = Buffer.concat([magic,Buffer.from([descriptor]),Buffer.alloc(30)])
  rows.push({id:`descriptor/${descriptor}`, scan:observed(() => scanZstdFrames(bytes))})
}
await writeFile(join(directory,'source.json'), JSON.stringify({node:process.versions.node, rows},null,2)+'\n')
console.log(JSON.stringify({directory,cases:rows.length}))

}
