import { writeFile } from 'node:fs/promises'
import { it } from 'vitest'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import { TestSessionQueryEngine } from '../../reference/packages/session-query/session-query/tests/test-service.ts'

it('observes one-shot lineage contracts and stack-independent descendants', async () => {
  const rows: any[] = []
  const names = ['root', 'complete', 'partial', 'cycle', 'self-cycle', 'missing', 'deep', 'unrelated-cycle',
    'persisted', 'listing-failure', 'foreign-rejection', 'pre-abort', 'list-abort', 'clone-detachment']
  for (const name of names) {
    const ctx = new Context()
    const controller = new AbortController()
    const failure: any = name === 'foreign-rejection' ? 'offline' : new TypeError('controlled lineage failure')
    const counters = {lists: 0, inspections: 0, sameSignal: false}
    const header = (id: string, createdAt = 1, parent?: string) => ({version: 0, id: SessionId(id), createdAt,
      ...parent === undefined ? {} : {parentSession: SessionId(parent)}})
    let headers: any[] = [header('target')]
    if (['complete','clone-detachment'].includes(name)) headers = [header('root',0),header('parent',1,'root'),
      header('target',2,'parent'),header('b',4,'target'),header('a',4,'target'),
      header('older',3,'target'),header('grandchild',5,'a')]
    if (name === 'partial') headers = [header('target',1,'outside')]
    if (name === 'cycle') headers = [header('target',1,'parent'),header('parent',2,'target')]
    if (name === 'self-cycle') headers = [header('target',1,'target')]
    if (name === 'unrelated-cycle') headers.push(header('x',2,'y'),header('y',3,'x'))
    if (name === 'deep') headers = [header('target',0), ...Array.from({length:3500}, (_,index) =>
      header('deep-' + (index + 1),index + 1,index === 0 ? 'target' : 'deep-' + index))]
    const record = (value: any) => ({id:value.header.id,createdAt:value.header.createdAt,
      parent:value.header.parentSession ?? null,live:value.live,persisted:value.persisted})
    const normalize = (trace: any) => {
      const descendants: any[] = []
      const pending = trace.descendants.map((node: any) => ({node,depth:1})).reverse()
      while (pending.length) {
        const {node,depth} = pending.pop()!
        descendants.push({...record(node.session),depth})
        pending.push(...node.descendants.map((child: any) => ({node:child,depth:depth + 1})).reverse())
      }
      return {keys:Object.keys(trace).sort(),target:record(trace.target),ancestors:trace.ancestors.map(record),
        complete:trace.complete,root:trace.root === undefined ? null : record(trace.root),
        unresolvedParentId:trace.unresolvedParentId ?? null,
        descendants:name === 'deep' ? {count:descendants.length,first:descendants[0],last:descendants.at(-1)} : descendants}
    }
    const observed: any = {}
    try {
      await ctx.plugin(SessionStore)
      if (!['persisted','listing-failure','foreign-rejection','pre-abort','list-abort'].includes(name))
        for (const meta of headers) ctx.sessions.enter(Session.create(meta.id,[],meta))
      if (['persisted','listing-failure','foreign-rejection','pre-abort','list-abort'].includes(name))
        ctx.provide('sessionPersistence',{
          list: async (signal: any) => {
            counters.lists += 1
            counters.sameSignal = signal === controller.signal
            if (['listing-failure','foreign-rejection'].includes(name)) throw failure
            if (name === 'list-abort') controller.abort(failure)
            return headers
          },
          inspect: async () => {counters.inspections += 1; throw new Error('unexpected inspection')},
        } as any)
      const query = new TestSessionQueryEngine(ctx)
      await Promise.resolve(); await Promise.resolve()
      if (name === 'pre-abort') controller.abort(failure)
      try {
        const trace = await query.traceSession(SessionId(name === 'missing' ? 'absent' : 'target'),controller.signal)
        observed.trace = normalize(trace)
        if (name === 'clone-detachment') {
          trace.target.header.createdAt = 99
          trace.ancestors[0]!.header.createdAt = 99
          if (trace.complete) trace.root.header.createdAt = 99
          trace.descendants[0]!.session.header.createdAt = 99
          observed.repeated = normalize(await query.traceSession(SessionId('target'),controller.signal))
          observed.sourceUnchanged = ctx.sessions.get(SessionId('target'))!.header.createdAt === 2
        }
      } catch (error: any) {
        observed.error = {name:error.name,message:error.message,code:error.code ?? null,
          sameCause:error.cause === failure,sameFailure:error === failure}
      }
      observed.counters = counters
      rows.push({name,observed})
    } finally {await ctx.fiber.dispose()}
  }
  await writeFile(process.env.SESSION_LINEAGE_OUTPUT!,JSON.stringify(rows,null,2) + '\n')
})
