import {spawn} from 'node:child_process'
import {once} from 'node:events'
import {existsSync,readFileSync,writeFileSync} from 'node:fs'
import {join} from 'node:path'
import {it} from 'vitest'
import {Client} from '@modelcontextprotocol/sdk/client/index.js'
import {ListToolsResultSchema,ToolListChangedNotificationSchema} from '@modelcontextprotocol/sdk/types.js'
import {z} from 'zod'
import {createTransport} from '../../reference/packages/mcp/mcp-client/src/transport.ts'

const modes = ['json','json-batch','json-bom','post-sse','sse-bom','get-sse','session','delete-405','status-401',
  'unexpected-content','missing-content','peer-error','cancel','timeout','close-pending','invalid-envelope']

it('observes actual source HTTP factory, SDK and owned peer wire', async () => {
  const rows: any[] = []
  for (const mode of modes) {
    const records = join(process.env.MCP_HTTP_DIRECTORY!,mode+'.json')
    const child = spawn(process.env.MCP_FIXTURE_PYTHON!,[process.env.MCP_HTTP_PEER!,mode,records],{stdio:'pipe'})
    const exited = once(child,'exit')
    let stderr = ''
    child.stderr.on('data',value => {stderr+=value})
    const url = await new Promise<string>((resolve,reject) => {
      let text = ''
      child.stdout.on('data',chunk => {text+=chunk;if (text.includes('\n')) resolve(text.split('\n')[0].trim())})
      child.on('error',reject)
    })
    const client = new Client({name:'dsh-mcp-client',version:'0.0.1'},{capabilities:{}})
    const transport = createTransport({transport:'streamable-http',url,headers:{Authorization:'controlled-local'}} as any)
    const row: any = {mode,notifications:[]}
    let closed = false
    client.onclose = () => {closed=true}
    client.setNotificationHandler(ToolListChangedNotificationSchema,packet => row.notifications.push(packet))
    try {
      await client.connect(transport)
      row.server = client.getServerVersion()
      const initializedDeadline = Date.now()+5000
      while (!existsSync(records+'.get')) {
        if (Date.now()>initializedDeadline) throw new Error('HTTP initialized GET not admitted')
        await new Promise(resolve => setTimeout(resolve,1))
      }
      row.tools = await client.request({method:'tools/list'},ListToolsResultSchema)
      const controller = new AbortController()
      const pending = client.request({method:'tools/call',params:{name:'echo',arguments:{text:'中文 controlled'}}},
        z.record(z.string(),z.unknown()),{signal:controller.signal,timeout:mode==='timeout' ? 100 : 60000})
      const settled = pending.then(value => ({result:value}),error => ({error}))
      const deadline = Date.now()+5000
      while (!existsSync(records+'.call')) {
        if (Date.now()>deadline) throw new Error('HTTP call not admitted')
        await new Promise(resolve => setTimeout(resolve,1))
      }
      if (mode==='cancel') controller.abort('controlled cancellation')
      if (mode==='close-pending') await client.close()
      const result = await settled
      if ('error' in result) throw result.error
      row.result = result.result
      while (!existsSync(records+'.get')) {
        if (Date.now()>deadline) throw new Error('HTTP initialized GET not admitted')
        await new Promise(resolve => setTimeout(resolve,1))
      }
      if (mode==='session' || mode==='delete-405') await (transport as any).terminateSession()
    } catch (error: any) {
      row.error = {name:error.name,message:error.message,...error.code===undefined ? {} : {code:error.code},
        ...error.data===undefined ? {} : {data:error.data}}
    } finally {
      let cleanupError: any
      try {
      if (mode==='cancel' || mode==='timeout') {
        const deadline = Date.now()+5000
        while (!existsSync(records+'.cancel')) {
          if (Date.now()>deadline) throw new Error('HTTP cancellation not admitted')
          await new Promise(resolve => setTimeout(resolve,1))
        }
      }
      } catch (error) {cleanupError=error}
      await client.close()
      child.stdin.end()
      const [code] = await exited
      if (code!==0 || stderr) throw new Error('Controlled HTTP peer failed: '+mode+' '+code+' '+stderr)
      if (cleanupError!==undefined) throw cleanupError
    }
    row.frames = JSON.parse(readFileSync(records,'utf8'))
    row.closed = closed
    row.reaped = child.exitCode===0 && child.signalCode===null
    rows.push(row)
  }
  writeFileSync(process.env.MCP_HTTP_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
},60000)
