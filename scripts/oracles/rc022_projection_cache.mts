/** Current Source cache/state consumers, using a v4 log and identity. */
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const source=process.argv[2]!,workspace=await readFile(process.argv[3]!,'utf8')
const load=(path:string)=>import(pathToFileURL(resolve(source,path)).href)
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:SessionStore,Session,SessionId}=await load('packages/core/session/src/index.ts')
const {default:SessionProjectionRegistry}=await load('packages/session/session-projection/src/index.ts')
const {default:Storage}=await load('packages/storage/storage/src/index.ts')
const {apply:jsonApply,Config:jsonConfig,inject:jsonInject}=await load('packages/storage/storage-json/src/index.ts')
const {apply:domainApply,Config:domainConfig,inject:domainInject}=await load('packages/storage/storage-domain/src/index.ts')
const {default:SessionProjectionCache}=await load('packages/session/session-projection-cache/src/index.ts')
  const output: any[] = []
  for (const name of ['cold-malformed', 'prepared-malformed', 'cold-matching', 'cold-foreign-identity',
    'cold-foreign-cwd', 'cold-version-mismatch', 'cold-beyond-log', 'cold-empty', 'prepared-runtime-malformed']) {
    const root = join(workspace, 'source', name)
    const document = join(root, 'session_projcache', 'sessions', 'owned.json')
    await mkdir(join(root, 'session_projcache', 'sessions'), {recursive: true})
    const header = {version: 4, id: SessionId('owned'), createdAt: 9, cwd: '/controlled/cwd',isSeeded:false}
    const record = {identity: {formatVersion: 4, isSeeded: false, inheritedEventCount: 0,
      createdAt: name === 'cold-foreign-identity' ? 8 : 9,
      cwd: name === 'cold-foreign-cwd' ? '/foreign/cwd' : header.cwd},
      rows: name === 'cold-empty' ? {} : {'controlled/count': {
        ver: name === 'cold-version-mismatch' ? 0 : 1, seq: name === 'cold-beyond-log' ? 2 : 0,
        val: name.endsWith('malformed') ? 'bad' : 7}}}
    await writeFile(document, JSON.stringify({version: 7, record}))
    const ctx = new Context()
    const applied: number[] = []
    const parserFailure = name === 'prepared-runtime-malformed'
      ? Object.assign(new Error('controlled runtime cache value'), {name: 'RuntimeError'})
      : new TypeError('controlled invalid cache value')
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
        if (name.startsWith('prepared-')) {
          observed.snapshot = ctx.sessionProjectionCache.hydratePrepared(Session.create(header.id, events, header), events)
        } else observed.snapshot = ctx.sessionProjectionCache.coldSnapshot(header, 0, events)
      } catch (error: any) {observed.error = {name: error.name, message: error.message, sameParserFailure: error === parserFailure}}
      await fiber.dispose()
      observed.applied = applied
      observed.document = JSON.parse(await readFile(document, 'utf8'))
      output.push({name, observed})
    } finally {await ctx.fiber.dispose()}
  }

process.stdout.write(JSON.stringify(output))
