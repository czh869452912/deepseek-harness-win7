import { mkdtempSync, readFileSync, existsSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { resolve, join } from 'node:path'
import { expect, it } from 'vitest'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { ListToolsResultSchema, ToolListChangedNotificationSchema } from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'
import { createTransport } from '../../reference/packages/mcp/mcp-client/src/transport.ts'

const modes = ['normal', 'notification', 'out-of-order', 'peer-error', 'peer-error-null',
  'cancel', 'timeout', 'eof', 'unsupported', 'capabilities-empty', 'missing-executable',
  'cap-logging-array', 'cap-experimental-false', 'tool-annotations-false', 'tool-properties-array', 'tool-unknown',
  'id-decimal', 'id-hex', 'id-empty', 'malformed-then-valid']

it('observes actual pinned stdio provider, SDK, cancellation and owned exit', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'mcp-sdk-observer-'))
  const observations = []
  try {
    for (const mode of modes) {
      const records = join(directory, mode + '.json')
      const client = new Client({name:'dsh-mcp-client', version:'0.0.1'}, {capabilities:{}})
      const notifications: unknown[] = []
      client.setNotificationHandler(ToolListChangedNotificationSchema, packet => {notifications.push(packet)})
      const transport = createTransport({transport:'stdio', serverName:'controlled',
        command:mode==='missing-executable' ? join(directory, 'missing-executable.exe') : process.env.MCP_FIXTURE_PYTHON!,
        args:[resolve(process.env.MCP_PEER_PATH!), mode, records], env:{}, cwd:process.cwd()} as any)
      const observed: any = {mode, notifications}
      if (mode === 'malformed-then-valid') {
        observed.protocolErrors = []
        client.onerror = error => {observed.protocolErrors.push({name:error.name,message:error.message})}
      }
      let ownedPid: number | null = null
      let resolveClosed: () => void
      const closed = new Promise<void>(resolve => {resolveClosed=resolve})
      try {
        const connecting = client.connect(transport)
        ownedPid = (transport as any).pid
        const previousClose = transport.onclose
        transport.onclose = () => {previousClose?.(); resolveClosed()}
        await connecting
        observed.server = client.getServerVersion()
        observed.tools = await client.request({method:'tools/list'}, ListToolsResultSchema)
        const call = (text='中文😀', options={}) => client.request({method:'tools/call',
          params:{name:'echo', arguments:{text}}}, z.record(z.string(), z.unknown()), options)
        if (mode==='out-of-order') observed.results = await Promise.all(Array.from({length:3}, (_, index) => call(String(index))))
        else if (mode==='cancel') {
          const controller = new AbortController()
          const pending = call('中文😀', {signal:controller.signal})
          const deadline = Date.now()+2000
          while (!existsSync(records + '.admitted')) {
            if (Date.now()>deadline) throw new Error('controlled request was not admitted')
            await new Promise(resolve => setTimeout(resolve,5))
          }
          controller.abort('controlled cancel')
          observed.results = [await pending]
        } else observed.results = [await call('中文😀', {timeout:mode==='timeout' ? 20 : 60000})]
      } catch (error: any) {observed.error = {message:error.message, code:error.code, data:error.data}}
      finally {
        await client.close()
        let deadline: ReturnType<typeof setTimeout> | undefined
        try {
          await Promise.race([closed, new Promise<void>((resolve,reject) => {
            deadline=setTimeout(() => reject(new Error('owned source transport did not close')),5000)
          })])
        } finally {if (deadline !== undefined) clearTimeout(deadline)}
      }
      observed.frames = existsSync(records) ? JSON.parse(readFileSync(records,'utf8')) : []
      observed.closed = (transport as any).pid === null
      observed.reaped = ownedPid === null
      if (ownedPid !== null) {
        try { process.kill(ownedPid, 0); observed.reaped = false }
        catch (error: any) { observed.reaped = error.code === 'ESRCH' }
      }
      observations.push(observed)
    }
    expect(observations).toHaveLength(modes.length)
    writeFileSync(process.env.MCP_OBSERVATIONS_OUTPUT!, JSON.stringify(observations,null,2)+'\n')
  } finally {rmSync(directory,{recursive:true,force:true})}
}, 30000)
