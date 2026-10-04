import {readFileSync, writeFileSync} from 'node:fs'
import {constants, zstdCompressSync, zstdDecompressSync} from 'node:zlib'
import {it} from 'vitest'
import {packChunkRuns, decodeStorageRecord, decodeSerializedChunkRow} from '../../reference/packages/session/session-persistence-sqlite/src/codec.ts'
import {bindRecord, decodeRow, scanRows} from '../../reference/packages/session/session-persistence-sqlite/src/compression.ts'

it('observes actual bounded schema-19 physical format and damaged history classification', () => {
  const input = JSON.parse(readFileSync(process.env.SQLITE_FORMAT_INPUT!, 'utf8'))
  const rows: any[] = []
  const observe = (name: string, operation: () => unknown) => {
    try { rows.push({name, value: operation()}) }
    catch (error: any) { rows.push({name, error: {name: error.name, message: error.message, code: error.code ?? null}}) }
  }
  for (const item of input.packs) observe(item.name, () => packChunkRuns(item.events))
  for (const item of input.decodes) observe(item.name, () => decodeStorageRecord(item.value))
  for (const item of input.varints.encode) observe(item.name, () => Buffer.from(bindRecord({seq: 100000,
    type: 'surface/event', time: 0, data: null, sourceEventSeqs: item.values} as any).sourceEventSeqs!).toString('hex'))
  for (const item of input.varints.decode) observe(item.name, () => (decodeRow({seq: item.seq, type: 'surface/event',
    time: 0, data: 'null', surface_op: null, source_event_seqs: Buffer.from(item.hex, 'hex'), is_packed: 0} as any)[0] as any).sourceEventSeqs)
  const physical = (bound: any) => ({seq: bound.seq, type: bound.type, time: bound.time, data: bound.data,
    source_event_seqs: bound.sourceEventSeqs, surface_op: bound.surfaceOp, is_packed: bound.isPacked})
  for (const [index, data] of input.compression.entries()) observe(`bind-${index}`, () => {
    const bound = bindRecord({seq: index, time: index, type: 'custom/event', data} as any)
    return {seq: bound.seq, time: bound.time, type: bound.type, isPacked: bound.isPacked,
      data: typeof bound.data === 'string' ? {text: bound.data} : {hex: Buffer.from(bound.data).toString('hex')}, decoded: decodeRow(physical(bound))}
  })
  const dictionary = readFileSync(new URL('../../reference/packages/session/session-persistence-sqlite/resources/zstd-dictionary.bin', import.meta.url))
  const encode = (value: Buffer, checksum = false) => zstdCompressSync(value, {dictionary,
    params: {[constants.ZSTD_c_compressionLevel]: 3, [constants.ZSTD_c_checksumFlag]: checksum ? 1 : 0}})
  const text = Buffer.from(JSON.stringify({text: 'x'.repeat(10000)}))
  const frame = encode(text)
  const checksum = encode(text, true)
  const damaged = Buffer.from(checksum)
  damaged[damaged.length - 1] ^= 1
  const frames = [
    {name: 'original-frame', hex: frame.toString('hex')}, {name: 'empty-frame', hex: ''},
    {name: 'unknown-header', hex: '00010203'}, {name: 'header-truncated', hex: frame.subarray(0, 4).toString('hex')},
    {name: 'tail-truncated', hex: frame.subarray(0, -1).toString('hex')}, {name: 'checksum-damaged', hex: damaged.toString('hex')},
    {name: 'invalid-utf8-bytes', hex: encode(Buffer.from([255, 254])).toString('hex')},
    {name: 'utf8-bom-bytes', hex: encode(Buffer.concat([Buffer.from([239, 187, 191]), Buffer.from('null')])).toString('hex')},
    {name: 'two-frames', hex: Buffer.concat([encode(Buffer.from('{')), encode(Buffer.from('}'))]).toString('hex')},
    {name: 'trailing-garbage', hex: Buffer.concat([frame, Buffer.from([0])]).toString('hex')},
    {name: 'packed-output-bound', hex: encode(Buffer.from(' '.repeat(1048577))).toString('hex'), maxOutputLength: 1048576},
  ]
  for (const item of frames) observe(item.name, () => zstdDecompressSync(Buffer.from(item.hex, 'hex'),
    {dictionary, ...('maxOutputLength' in item ? {maxOutputLength: item.maxOutputLength} : {})}).toString('hex'))
  const start = physical(bindRecord({type: 'turn/start', seq: 0, time: 1, data: {turn: 1}} as any))
  const end = physical(bindRecord({type: 'turn/end', seq: 2, time: 3, data: {turn: 1, reason: {kind: 'completed'}}} as any))
  const invalid = {...start, seq: 1, data: '{not json'}
  const gap = {...start, seq: 2}
  observe('scan-empty', () => scanRows([]))
  observe('scan-valid', () => scanRows([start]))
  observe('scan-invalid-tail', () => scanRows([start, invalid]))
  observe('scan-invalid-committed', () => scanRows([start, invalid, end]))
  observe('scan-gap-tail', () => scanRows([start, gap]))
  observe('scan-gap-committed', () => scanRows([start, gap, {...end, seq: 3}]))
  observe('scan-nonzero-base', () => scanRows([{...start, seq: 100}], 100))
  observe('packed-unknown-tag', () => decodeRow({...start, is_packed: 1}))
  observe('packed-surface-refusal', () => decodeRow({...start, type: 'text-chunks', is_packed: 1, source_event_seqs: Buffer.alloc(0)}))
  observe('serialized-byte-limit', () => decodeSerializedChunkRow('text-chunks', 0, 0, ' '.repeat(1048577)))
  observe('serialized-surrogate-byte-limit', () => decodeSerializedChunkRow('text-chunks', 0, 0, '\ud800'.repeat(349526)))
  writeFileSync(process.env.SQLITE_FORMAT_OUTPUT!, JSON.stringify({node: process.version, zstd: process.versions.zstd, frames, rows}))
})
