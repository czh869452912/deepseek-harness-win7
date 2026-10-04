import {writeFileSync} from 'node:fs'
import {it} from 'vitest'
import {apply} from '../../reference/packages/session-query/tool-session-query/src/index.ts'
import {toolInput} from '../../reference/packages/session-query/tool-session-query/src/input.ts'
import {SessionQueryError, filterSessionResults} from '@deepseek-ai/dsh-session-query'
import {HarnessError} from '@deepseek-ai/dsh-llm'
import {serviceBoundary} from '../../reference/packages/session-query/tool-session-query/src/service-boundary.ts'


it('observes the actual optional tool consumer and its input contracts', async () => {
  const rows: unknown[] = []
  const observe = async (name: string, invoke: () => unknown) => {
    try { rows.push({name, value: await invoke()}) }
    catch (error) { rows.push({name, error: {code: (error as any)?.code ?? null, message: (error as any)?.message ?? String(error)}}) }
  }
  for (const [index, query] of ['\ufeff  needle\u00a0second\u2028', 'literal.* []', '\u001c', '  ', '\ufeff', 'bad\0query'].entries()) {
    await observe(`query-${index}`, () => toolInput.normalizeQuery(query))
  }
  for (const [index, instant] of [
    '1970-01-01T00:00:00.0000001Z', '1969-12-31T23:59:59.9999999Z', '2026-07-24T00:00:00.12300001Z',
    '2026-07-24T08:00:00.1239999+08:00', '0000-02-29T00:00Z', '0099-12-31T23:59:59-23:59',
    '9999-12-31T23:59:59.99999999Z', '2000-02-29T00:00Z', '2100-02-29T00:00Z',
    '2026-02-30T10:00:00Z', '2026-01-01T24:00:00Z', '2026-01-01T00:00:00+24:00',
    '2026-07-24T10:00:00', '2026-07-24T10:00:00Z\n',
  ].entries()) {
    await observe(`timestamp-${index}`, () => toolInput.buildSessionFilters({query: 'q', created_at_from: instant, created_at_to: instant}))
  }
  for (const [index, range] of [
    ['2026-07-24T00:00:00.1231Z', '2026-07-24T00:00:00.12311Z'],
    ['2026-07-24T00:00:00.12311Z', '2026-07-24T00:00:00.1231Z'],
    ['2026-07-24T00:00:00.1230000100Z', '2026-07-24T00:00:00.12300001Z'],
    ['1969-12-31T23:59:59.87600001Z', '1969-12-31T19:59:59.8769999-04:00'],
  ].entries()) {
    await observe(`range-${index}`, () => toolInput.buildSessionFilters({query: 'q', created_at_from: range[0], created_at_to: range[1]}))
  }
  const records = [
    {header: {id: 'caller', version: 2, createdAt: 10, cwd: '/work'}, live: true, persisted: false},
    {header: {id: 'a', version: 2, createdAt: 100, cwd: '/work', parentSession: 'hidden'}, live: true, persisted: true},
    {header: {id: 'b', version: 2, createdAt: 101, cwd: '/work'}, live: false, persisted: true},
    {header: {id: 'hidden', version: 2, createdAt: 102, cwd: '/outside'}, live: true, persisted: false},
  ]
  const definitions: any[] = [], sections: unknown[] = [], calls: unknown[] = [], warnings: string[] = []
  const controller = new AbortController()
  const signal = controller.signal
  let scenario = '', page = 0
  const record = (method: string, payload: unknown, provided: AbortSignal | undefined) => calls.push({method, payload, sameSignal: provided === signal})
  const hit = (id: string) => ({...records.find(record => record.header.id === id), bestMatch: {
    sessionId: id, seq: 4, type: 'assistant/message', time: 200, surface: 'current', snippet: 'needle excerpt',
  }})
  const target = {seq: 1, time: 200, type: 'user/message', data: {id: 'msg', role: 'user', content: [{type: 'text', text: 'first\nsecond'}], source: {kind: 'user'}}}
  const query = {
    async filterSessions(filters: any, provided: AbortSignal) {
      record('filterSessions', filters, provided)
      return filterSessionResults(records as any, filters)
    },
    async searchSessions(request: any, execution: any) {
      record('searchSessions', request, execution.signal)
      if (scenario === 'private-failure') throw new SessionQueryError('private provider /secret/path', 'SESSION_QUERY_INDEX_FAILED')
      if (scenario === 'foreign-failure') throw {code: 'SESSION_QUERY_INDEX_FAILED', toString: () => 'private foreign failure'}
      if (scenario === 'repeated-cursor') return {items: [], nextCursor: 'same'}
      if (scenario === 'pages') return page++ === 0 ? {items: [hit('caller'), hit('hidden')], nextCursor: 'page-1'} :
        page === 2 ? {items: [hit('a')], nextCursor: 'page-2'} : {items: [hit('b'), hit('a')]}
      return {items: []}
    },
    async searchEvents(request: any, execution: any) {
      record('searchEvents', request, execution.signal)
      return {session: records[0].header, items: [{sessionId: 'caller', seq: 1, type: 'user/message', time: 201, surface: 'current', snippet: 'needle'}]}
    },
    async readTitleSnapshots(ids: string[], provided: AbortSignal) {
      record('readTitleSnapshots', ids, provided)
      return ids.map(sessionId => ({sessionId, status: 'fulfilled', value: {session: records.find(record => record.header.id === sessionId)!.header}}))
    },
    async traceSession(id: string, provided: AbortSignal) {
      record('traceSession', id, provided)
      return {target: records[0], ancestors: [records[3]], complete: true, descendants: [
        {session: records[1], descendants: [{session: records[3], descendants: [{session: records[2], descendants: []}]}]},
        {session: records[2], descendants: []},
      ]}
    },
    async traceEvent(request: any, provided: AbortSignal) {
      record('traceEvent', request, provided)
      return {session: records[0].header, target: {seq: 1, type: 'user/message', time: 200, surface: 'shadowed'},
        replacedBy: 4, replacementChain: [4, 6], replacedEventSeqs: [0], sourceEventSeqs: [0, 2], derivedEventSeqs: [3, 5]}
    },
    async readEvent(request: any, provided: AbortSignal) {
      record('readEvent', request, provided)
      return {session: records[0].header, target, events: [{seq: 0, time: 100, type: 'step/start', data: {turn: 1, step: 1}}, target,
        {seq: 2, time: 300, type: 'assistant/message', data: {message: {id: 'reply', role: 'assistant', content: [{type: 'text', text: 'reply'}]}}}]}
    },
  }
  const ctx: any = {tools: {register: (definition: unknown) => definitions.push(definition)},
    systemPrompt: {section: (section: unknown) => sections.push(section)}, sessionQuery: query,
    logger: {warn: (message: string) => warnings.push(message)}}
  apply(ctx, {maxSearchResults: 2, searchTimeoutMs: 1234})
  rows.push({name: 'registration', value: {sections: [...sections], tools: definitions.map(definition => ({name: definition.name,
    description: definition.description, parameters: definition.parameters, output: definition.output.schema,
    timeoutMs: definition.timeoutMs ?? null, concurrencySafe: definition.isConcurrencySafe?.({seq: 1}) ?? null}))}})
  const execution: any = {signal, agent: {session: {id: 'caller', header: records[0].header,
    events: [{seq: 0, type: 'turn/start'}, {seq: 1, type: 'user/message'}, {seq: 2, type: 'step/start'}]}}}
  for (const [name, toolName, args] of [
    ['empty', 'session_search', {query: 'q'}], ['pages', 'session_search', {query: 'q'}],
    ['private-failure', 'session_search', {query: 'q'}], ['foreign-failure', 'session_search', {query: 'q'}],
    ['repeated-cursor', 'session_search', {query: 'q'}], ['prior-events', 'session_event_search', {query: 'needle'}],
    ['empty-step-range', 'session_event_search', {query: 'q', seq_from: 2}],
    ['unauthorized-before-query', 'session_event_search', {query: ' ', session_id: 'hidden'}],
    ['lineage', 'session_trace', {}], ['relationships', 'session_event_trace', {seq: 1}],
    ['exact-read', 'session_event_read', {seq: 1, before: 1, after: 1}],
    ['invalid-schema', 'session_event_read', {seq: '1'}], ['invalid-integer', 'session_event_trace', {seq: -1}],
  ] as Array<[string, string, any]>) {
    scenario = name; page = 0; calls.length = 0; warnings.length = 0
    const definition = definitions.find(definition => definition.name === toolName)
    await observe(name, async () => ({output: await definition.execute(args, execution), calls: [...calls]}))
    rows.push({name: name + '-metadata', value: {calls: [...calls], warningPrivate: warnings.some(message => message.includes('private')),
      call: definition.presentCall?.(args) ?? null}})
  }
  for (const [index, code] of ['SESSION_QUERY_ABORTED', 'SESSION_QUERY_CORRUPT_SESSION', 'SESSION_QUERY_EVENT_NOT_FOUND',
    'SESSION_QUERY_INDEX_FAILED', 'SESSION_QUERY_INVALID_CONFIG', 'SESSION_QUERY_INVALID_CURSOR', 'SESSION_QUERY_INVALID_FILTER',
    'SESSION_QUERY_INVALID_LIMIT', 'SESSION_QUERY_INVALID_QUERY', 'SESSION_QUERY_INVALID_LINEAGE', 'SESSION_QUERY_INVALID_SURFACE',
    'SESSION_QUERY_INVALID_WINDOW', 'SESSION_QUERY_PERSISTENCE_FAILED', 'SESSION_QUERY_SEARCH_DISABLED', 'SESSION_QUERY_SESSION_NOT_FOUND',
    'SESSION_QUERY_STALE_CURSOR', 'SESSION_QUERY_SOURCE_CONFLICT', 'FOREIGN_CODE'].entries()) {
    warnings.length = 0
    const error = new SessionQueryError('private provider diagnostic', code as any)
    const sanitized = serviceBoundary.sanitizeError(ctx, 'failure matrix', error)
    rows.push({name: `failure-${index}`, value: {code: sanitized.code, message: sanitized.message,
      privateLogged: warnings.some(message => message.includes('private provider diagnostic'))}})
  }
  for (const [index, config] of [{maxSearchResults: 0}, {maxSearchResults: true}, {maxSearchResults: 9007199254740992},
    {searchTimeoutMs: 2147483648}, {searchTimeoutMs: 1.5}, {maxSearchResults: null, searchTimeoutMs: null}].entries()) {
    await observe(`config-${index}`, () => { apply(ctx, config as any); return 'accepted' })
  }
  for (const fails of [false, true]) {
    const cancellation = new AbortController()
    const reason = new HarnessError('caller cancellation', 'CALLER_CANCELLED')
    let completed = false
    warnings.length = 0
    await observe(`abort-${fails}`, async () => {
      try {
        await serviceBoundary.call(ctx, cancellation.signal, 'pending provider', async () => {
          await Promise.resolve()
          completed = true
          cancellation.abort(reason)
          if (fails) throw new SessionQueryError('private late provider failure', 'SESSION_QUERY_INDEX_FAILED')
          return 'late result'
        })
        return 'unexpected result'
      } catch (error) {
        return {sameReason: error === reason, completed, warnings: [...warnings]}
      }
    })
  }
  rows.push({name: 'harness-error-kind', value: new HarnessError('message', 'CODE').name})
  writeFileSync(process.env.SESSION_TOOLS_OUTPUT!, JSON.stringify({node: process.version, rows}, null, 2))
})
