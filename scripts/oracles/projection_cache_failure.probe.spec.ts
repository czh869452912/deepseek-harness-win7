import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import SessionProjectionRegistry from '@deepseek-ai/dsh-session-projection'
import Storage from '@deepseek-ai/dsh-storage'
import { apply as jsonApply, Config as jsonConfig, inject as jsonInject } from '@deepseek-ai/dsh-storage-json'
import { apply as domainApply, Config as domainConfig, inject as domainInject } from '@deepseek-ai/dsh-storage-domain'
import SessionProjectionCache from '../../reference/packages/session/session-projection-cache/src/index.ts'

it('observes real durable cache schema failures separately from prepared fallback', async () => {
  const output: any[] = []
  for (const name of ['cold-malformed', 'prepared-malformed', 'cold-matching', 'cold-foreign-identity',
    'cold-foreign-cwd', 'cold-version-mismatch', 'cold-beyond-log', 'cold-empty']) {
    const root = join(process.env.PROJECTION_CACHE_WORKSPACE!, name)
    const document = join(root, 'session_projcache', 'sessions', 'owned.json')
    await mkdir(join(root, 'session_projcache', 'sessions'), {recursive: true})
    const header = {version: 0, id: SessionId('owned'), createdAt: 9, cwd: '/controlled/cwd'}
    const record = {identity: {createdAt: name === 'cold-foreign-identity' ? 8 : 9,
      cwd: name === 'cold-foreign-cwd' ? '/foreign/cwd' : header.cwd},
      rows: name === 'cold-empty' ? {} : {'controlled/count': {
        ver: name === 'cold-version-mismatch' ? 0 : 1, seq: name === 'cold-beyond-log' ? 2 : 0,
        val: name.endsWith('malformed') ? 'bad' : 7}}}
    await writeFile(document, JSON.stringify({version: 4, record}))
    const ctx = new Context()
    const applied: number[] = []
    const parserFailure = new TypeError('controlled invalid cache value')
    const schema = {parse(value: unknown) {if (typeof value !== 'number') throw parserFailure; return value}}
    try {
      await ctx.plugin(Storage)
      await ctx.plugin({name: 'controlled-json', inject: jsonInject, apply: jsonApply, Config: jsonConfig}, {root})
      await ctx.plugin({name: 'controlled-domain', inject: domainInject, apply: domainApply, Config: domainConfig}, {backend: 'json'})
      await ctx.plugin(SessionStore)
      await ctx.plugin(SessionProjectionRegistry)
      ctx.sessionProjections.register({key: 'controlled/count', stateVersion: 1, stateSchema: schema,
        init: () => 0, apply: (state: number, event: any) => {applied.push(event.seq); return state + 1},
        wire: {viewSchema: schema, view: (state: number) => state}} as any)
      const fiber = await ctx.plugin(SessionProjectionCache, {writeEveryEvents: 100, writeIntervalMs: 60000})
      const events = [0, 1].map(seq => ({type: 'controlled/event', seq, time: seq, data: {}})) as any
      const observed: any = {}
      try {
        if (name === 'prepared-malformed') {
          observed.snapshot = ctx.sessionProjectionCache.hydratePrepared(Session.create(header.id, events, header), header, events)
        } else observed.snapshot = ctx.sessionProjectionCache.coldSnapshot(header, events)
      } catch (error: any) {observed.error = {name: error.name, message: error.message, sameParserFailure: error === parserFailure}}
      await fiber.dispose()
      observed.applied = applied
      observed.document = JSON.parse(await readFile(document, 'utf8'))
      output.push({name, observed})
    } finally {await ctx.fiber.dispose()}
  }
  await writeFile(process.env.PROJECTION_CACHE_OUTPUT!, JSON.stringify(output, null, 2) + '\n')
}, 30000)
