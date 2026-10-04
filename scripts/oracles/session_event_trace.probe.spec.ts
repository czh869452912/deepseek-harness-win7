import { readFile, writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import { TestSessionQueryEngine } from '../../reference/packages/session-query/session-query/tests/test-service.ts'

it('observes exact surface, event traces and raw windows', async () => {
  const fixture = JSON.parse(await readFile('scripts/oracles/session_event_trace_fixture.json','utf8'))
  const rows: any[] = []
  const names = ["trace-original","trace-replacement","trace-log-only","trace-current","trace-detachment","surface-live","surface-cold","surface-empty","surface-invalid","list-records","list-invalid","trace-missing-before-invalid","trace-invalid-surface","trace-duplicate-sources","trace-non-surface-source","window-target","window-default","window-clamped","window-alias","window-invalid-before","window-invalid-after","window-invalid-limit","window-before-abort","trace-pre-abort","trace-list-failure","trace-inspect-failure","trace-foreign-failure","trace-header-conflict","trace-attach-wins","read-session-adoption"]
  for (const name of names) {
    const ctx = new Context()
    const controller = new AbortController()
    const failure: any = name === 'trace-foreign-failure' ? 'offline' : new TypeError('controlled event failure')
    const counters = {lists:0,inspections:0,sameSignal:true}
    const meta = {version:0,id:SessionId('owned'),createdAt:9,cwd:'/controlled/cwd'}
    let events = structuredClone(fixture)
    if (name === 'surface-empty') events = []
    if (['surface-invalid','list-invalid','trace-missing-before-invalid','trace-invalid-surface'].includes(name))
      events[2].surfaceOp.start = 99
    if (name === 'trace-duplicate-sources') events[3].sourceEventSeqs = [0,0]
    if (name === 'trace-non-surface-source') events[0].sourceEventSeqs = [0]
    const normalizeEvent = (event: any) => ({seq:event.seq,type:event.type,time:event.time,
      text:event.data.content?.[0]?.text ?? null})
    const observed: any = {}
    try {
      await ctx.plugin(SessionStore)
      const live = ['trace-original','trace-replacement','trace-log-only','trace-current','trace-detachment',
        'surface-live','list-records','window-target','window-default','window-clamped','window-alias',
        'read-session-adoption'].includes(name)
      if (live) ctx.sessions.enter(Session.create(meta.id,events,meta))
      else ctx.provide('sessionPersistence',{
        list: async (signal: any) => {
          counters.lists += 1
          counters.sameSignal &&= signal === (['trace-pre-abort','window-before-abort',
            'trace-list-failure','trace-inspect-failure','trace-foreign-failure','trace-header-conflict',
            'trace-attach-wins'].includes(name) ? controller.signal : undefined)
          if (name === 'trace-list-failure') throw failure
          return [meta]
        },
        inspect: async (_id: string, signal: any) => {
          counters.inspections += 1
          counters.sameSignal &&= signal === (['trace-inspect-failure','trace-foreign-failure',
            'trace-header-conflict','trace-attach-wins'].includes(name) ? controller.signal : undefined)
          if (['trace-inspect-failure','trace-foreign-failure'].includes(name)) throw failure
          if (name === 'trace-attach-wins') ctx.sessions.enter(Session.create(meta.id,events,meta))
          return {meta:{...meta,cwd:name === 'trace-header-conflict' ? '/foreign' : meta.cwd},events}
        },
      } as any)
      const query = new TestSessionQueryEngine(ctx,{readWindowMax:name === 'window-invalid-limit' ? 2 : 50})
      await Promise.resolve(); await Promise.resolve()
      if (['trace-pre-abort','window-before-abort'].includes(name)) controller.abort(failure)
      try {
        if (name.startsWith('surface-')) {
          const value = await query.readSurface(meta.id)
          observed.surface = {id:value.session.id,capturedThroughSeq:value.capturedThroughSeq,events:value.events.map(normalizeEvent)}
          if (value.events.length) {
            try {value.events[0]!.data.content[0]!.text = 'foreign'} catch (error) {observed.messageMutationRefused = error instanceof TypeError}
          }
        } else if (name.startsWith('list-')) {
          observed.records = await query.listEvents(meta.id)
        } else if (name.startsWith('window-')) {
          const request: any = {sessionId:meta.id,seq:2}
          if (['window-target','window-alias'].includes(name)) {request.before=1;request.after=1}
          if (name === 'window-clamped') {request.seq=0;request.before=50;request.after=50}
          if (['window-invalid-before','window-before-abort'].includes(name)) request.before=-1
          if (name === 'window-invalid-after') request.after=true
          if (name === 'window-invalid-limit') request.after=3
          const value = await query.readEvent(request,name === 'window-before-abort' ? controller.signal : undefined)
          observed.window = {id:value.session.id,target:normalizeEvent(value.target),events:value.events.map(normalizeEvent),
            startSeq:value.startSeq,endSeq:value.endSeq}
          observed.targetAlias = value.events[request.seq-value.startSeq] === value.target
          if (name === 'window-alias') {
            try {value.target.data.content[0]!.text = 'foreign'} catch (error) {observed.messageMutationRefused = error instanceof TypeError}
            value.target.time=99
            observed.aliasTime=value.events[request.seq-value.startSeq]!.time
            observed.sourceTime=ctx.sessions.get(meta.id)!.events[request.seq]!.time
          }
        } else if (name === 'read-session-adoption') {
          const value = await query.readSession(meta.id)
          try {value.events[1]!.data.content[0]!.text = 'foreign'} catch (error) {observed.messageMutationRefused = error instanceof TypeError}
          value.events[1]!.time=99
          observed.sourceTime=ctx.sessions.get(meta.id)!.events[1]!.time
          observed.log=value.events.map(normalizeEvent)
        } else {
          const seq = name === 'trace-replacement' || name === 'trace-detachment' ? 2
            : name === 'trace-log-only' || name === 'trace-invalid-surface' ? 0
            : name === 'trace-current' ? 4 : name === 'trace-missing-before-invalid' ? 99 : 1
          const signal = ['trace-pre-abort','trace-list-failure','trace-inspect-failure','trace-foreign-failure',
            'trace-header-conflict','trace-attach-wins'].includes(name) ? controller.signal : undefined
          const value = await query.traceEvent({sessionId:meta.id,seq},signal)
          const {session,...trace} = value
          observed.trace={id:session.id,...trace}
          if (name === 'trace-detachment') {
            value.target.time=99
            value.replacementChain.push(99)
            value.replacedEventSeqs.push(99)
            value.sourceEventSeqs.push(99)
            value.derivedEventSeqs.push(99)
            const {session:repeatedHeader,...repeated} = await query.traceEvent({sessionId:meta.id,seq})
            observed.repeated={id:repeatedHeader.id,...repeated}
          }
        }
      } catch (error: any) {
        observed.error={name:error.name,message:error.message,code:error.code ?? null,
          sameCause:error.cause === failure,sameFailure:error === failure,
          causeMessage:error.cause instanceof Error ? error.cause.message : null}
      }
      observed.counters=counters
      rows.push({name,observed})
    } finally {await ctx.fiber.dispose()}
  }
  await writeFile(process.env.SESSION_EVENT_TRACE_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
