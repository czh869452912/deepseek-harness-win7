import { it } from 'vitest'
import { writeFileSync } from 'node:fs'
import { Context } from '@deepseek-ai/cordis'
import SessionStore, { Session, SessionId } from '@deepseek-ai/dsh-session'
import Registry from '@deepseek-ai/dsh-session-projection'
import { z } from 'zod'

it('observes real registry drive, ownership and restoration', async () => {
  const ctx = new Context()
  await ctx.plugin(SessionStore)
  await ctx.plugin(Registry)
  const reg = ctx.sessionProjections
  const unit = (key = 'probe', wire = true): any => ({ key, stateVersion: 1,
    stateSchema: z.number().int().nonnegative(), init: () => 0, apply: (state: number) => state + 1,
    ...(wire ? { wire: { viewSchema: z.number().int(), view: (state: number) => state } } : {}),
  })
  const rows: any[] = [], changes: any[] = []
  const session = ctx.sessions.create(SessionId('probe'))
  session.append('probe/event' as any, {})
  const release = reg.register(unit())
  const shared = reg.register(unit())
  reg.onChanged((_session, key, value, seq) => changes.push({key,value,seq}))
  session.append('probe/event' as any, {})
  rows.push({mode:'late', snapshot:reg.snapshot(session), changes:[...changes]})
  release(); release()
  rows.push({mode:'shared',snapshot:reg.snapshot(session)})
  const second = Session.create(SessionId('probe'))
  rows.push({mode:'identity',snapshot:reg.snapshot(second)})
  reg.register(unit('host', false))
  rows.push({mode:'selected',snapshot:reg.snapshot(session, []),checkpoint:reg.checkpoint(session)})
  const checkpoint = reg.checkpoint(session)
  checkpoint.probe!.val = 99
  rows.push({mode:'detached',snapshot:reg.snapshot(session),floor:reg.restoreFloor(checkpoint)})
  const events = session.events
  const restored = reg.restore({}, events, 0, session.header)
  rows.push({mode:'restore',...restored,empty:reg.restore(restored.checkpoint, [], session.seq, session.header)})
  let truncated = false, invalid = false
  try { reg.restore(restored.checkpoint, [], 1, session.header) } catch { truncated = true }
  try { reg.register({...unit(),stateVersion:2}) } catch { invalid = true }
  rows.push({mode:'guards',truncated,invalid,hints:reg.viewCheckpoint({probe:{ver:1,seq:1,val:'bad'}})})
  const prepared = Session.create(SessionId('prepared'))
  prepared.append('probe/event' as any,{})
  prepared.append('probe/event' as any,{})
  const prefix = prepared.events.slice(0,1)
  const hydrated = reg.hydrate(prepared, {}, prefix, 0)
  const again = reg.hydrate(prepared, {}, prefix, 0)
  rows.push({mode:'hydrate',hydrated,again,snapshot:reg.snapshot(prepared)})
  shared()
  rows.push({mode:'unregistered',snapshot:reg.snapshot(session)})
  writeFileSync(process.env.SESSION_PROJECTION_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
  await ctx.fiber.dispose()
})
