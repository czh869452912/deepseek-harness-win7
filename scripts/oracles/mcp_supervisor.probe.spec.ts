import {writeFileSync} from 'node:fs'
import {it,vi} from 'vitest'

const fixture = vi.hoisted(() => ({scenario:'',trace:[] as any[],clients:[] as any[],fetches:0}))
vi.mock('@modelcontextprotocol/sdk/client/index.js', () => ({Client:class {
  onclose: any
  notify: any
  constructor() {fixture.clients.push(this);fixture.trace.push(['create',fixture.clients.length])}
  setNotificationHandler(_schema:any,callback:any) {this.notify=callback}
  async connect() {
    fixture.trace.push(['connect'])
    if (fixture.scenario.startsWith('connect-failure')) throw new Error('controlled connect failure')
  }
  async close() {fixture.trace.push(['close']);this.onclose?.()}
  async request(packet:any) {
    fixture.trace.push(['fetch',packet.method]);fixture.fetches++
    if (fixture.scenario==='notification-failure' && fixture.fetches>1) throw new Error('controlled fetch failure')
    return {tools:[{name:'echo',inputSchema:{type:'object'}}]}
  }
}}))
vi.mock('@modelcontextprotocol/sdk/client/stdio.js', () => ({StdioClientTransport:class {}}))

import {startConnection} from '../../reference/packages/mcp/mcp-client/src/connection.ts'

it('records source supervisor readiness, diagnostics and owned registry ordering', async () => {
  const rows: any[] = []
  for (const scenario of ['success','connect-failure-disabled','connect-failure-exhaust',
    'close-disabled','close-retry','notification-success','notification-failure','registration-contain','registration-throw']) {
    Object.assign(fixture,{scenario,trace:[],clients:[],fetches:0})
    const logs: any[] = [], registered = new Set<string>()
    const tools = {register:(definition:any) => {
      fixture.trace.push(['register',definition.name])
      if (scenario.startsWith('registration-')) throw new Error('controlled registration failure')
      registered.add(definition.name)
      return () => {fixture.trace.push(['unregister',definition.name]);registered.delete(definition.name)}
    }}
    const ctx = {tools,get:(name:string) => name==='tools' ? tools : undefined,
      logger:Object.fromEntries(['warn','error','info'].map(level => [level,(message:string) => logs.push([level,message])]))}
    const enabled = ['connect-failure-exhaust','close-retry'].includes(scenario)
    const handle = startConnection(ctx as any,{transport:'stdio',serverName:'controlled',command:'unused',args:[],env:{},cwd:'',
      toolCallTimeoutMs:60000,failOnStartupError:scenario==='registration-throw'} as any,
      {enabled,initialDelayMs:1,maxDelayMs:1000,maxAttempts:1})
    const outcome = await handle.ready
    if (scenario.startsWith('close-')) fixture.clients[0].onclose()
    if (scenario.startsWith('notification-')) await fixture.clients[0].notify({method:'notifications/tools/list_changed'})
    if (enabled) {
      for (let index=0;index<100 && fixture.clients.length<2;index++) await new Promise(resolve => setTimeout(resolve,1))
      for (let index=0;index<10;index++) await Promise.resolve()
    }
    const before = [...registered]
    await handle.dispose()
    rows.push({scenario,outcome:outcome.error===undefined ? {} : {error:{name:outcome.error.name,message:outcome.error.message}},
      before,after:[...registered],trace:fixture.trace,logs})
  }
  writeFileSync(process.env.MCP_SUPERVISOR_OUTPUT!,JSON.stringify(rows,null,2)+'\n')
})
