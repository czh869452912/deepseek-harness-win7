import {writeFileSync} from 'node:fs'
import {it} from 'vitest'
import {publicToolName, syncTools} from '../../reference/packages/mcp/mcp-client/src/tools.ts'

it('observes actual bridge names, raw results and native text projection', async () => {
  const observations = []
  for (const rawName of ['echo', '中文', '😀', '\ud800', 'x'.repeat(70), 'a😀b', 'a b']) {
    observations.push({kind:'name',rawName,result:publicToolName('controlled',rawName)})
  }
  const contents = [[], [null, false, [], {}], [{type:'text',text:null},{type:'text',text:false},{type:'text',text:{value:1}}],
    [{type:'resource_link'},{type:'resource_link',name:null,uri:null}], [{type:'image',mimeType:null}],
    [{type:'audio',mimeType:null},{type:'resource'},{type:null},{}],
    [{type:'text',text:'before'},{type:'image',mimeType:'image/png',data:'invalid'},{type:'text',text:'after'}]]
  for (const content of contents) {
    let definition: any
    const client = {request: async (request: any) => request.method === 'tools/list'
      ? {tools:[{name:'echo',inputSchema:{type:'object'}}]} : {content}}
    const ctx = {tools:{register:(value: any) => {definition=value;return () => {}}},get:() => undefined,logger:{error:() => {}}}
    const disposers = await syncTools(client as any,ctx as any,{serverName:'controlled',toolCallTimeoutMs:60000},new Map())
    const execution = {signal:new AbortController().signal}
    const value = await definition.execute({}, execution)
    const fallback = definition.output.render({},value)
    const final = definition.finalizeContent(execution, {value,content:fallback,isError:false})
    observations.push({kind:'content',content,value,fallback,...final===undefined ? {} : {final}})
    for (const dispose of disposers.values()) dispose()
  }
  const image = {type:'image',mimeType:'image/png',data:'AQID'}
  for (const scenario of ['positive','header-route','no-attachments','no-llm','no-agent','unverified',
    'missing-modalities','text-model','aborted','abort-resolve','admission','storage','unknown-code',
    'invalid-mime','invalid-base64','base64-alias','empty-base64','mixed-invalid',
    'result-error','replaced-value','boolean-number','changed-content','foreign-execution','concurrent']) {
    let definition: any
    const trace: any[] = []
    const controller = new AbortController()
    const content: any[] = [{type:'text',text:'before'}, {...image}, {type:'text',text:'after'}]
    if (scenario === 'invalid-mime') content[1].mimeType = 'image/svg+xml'
    if (scenario === 'invalid-base64') content[1].data = 'AQI'
    if (scenario === 'base64-alias') content[1].data = 'AB=='
    if (scenario === 'empty-base64') content[1].data = ''
    if (scenario === 'mixed-invalid') content.push({...image,data:'bad'}, {...image})
    const raw = {content,structuredContent:{flag:false}}
    const client = {request: async (request: any) => request.method === 'tools/list'
      ? {tools:[{name:'echo',inputSchema:{type:'object'}}]} : raw}
    const attachments = {saveImages:async (images: any[]) => {
      trace.push({save:images.map(value => ({data:value.data.toString('base64'),mediaType:value.mediaType}))})
      if (['admission','storage','unknown-code'].includes(scenario)) {
        throw Object.assign(new Error('controlled storage failure'), {code:scenario==='admission' ? 'INVALID_IMAGE' : scenario==='storage' ? 'ATTACHMENT_WRITE_FAILED' : 'OTHER'})
      }
      return images.map((_value,index) => ({attachmentId:'controlled-'+index,mediaType:'image/png',bytes:3,width:1,height:1}))
    }}
    const llm = {resolveModelInfo:async (provider: any,model: any,signal: any) => {
      trace.push({route:[provider,model],ownedSignal:signal===controller.signal})
      if (scenario==='unverified') throw new Error('controlled route failure')
      if (scenario==='abort-resolve') controller.abort()
      return scenario==='missing-modalities' ? {} : {inputModalities:scenario==='text-model' ? ['text'] : ['text','image']}
    }}
    const ctx = {tools:{register:(value:any) => {definition=value;return () => {}}},
      get:(name:string) => name==='attachments' && scenario!=='no-attachments' ? attachments
        : name==='llm' && scenario!=='no-llm' ? llm : undefined,logger:{error:() => {}}}
    const disposers = await syncTools(client as any,ctx as any,{serverName:'controlled',toolCallTimeoutMs:60000},new Map())
    const execution = {signal:controller.signal,...scenario==='no-agent' ? {} : {agent:{
      session:{requestHeader:() => scenario==='header-route' ? {config:{provider:'header',model:'vision'}} : undefined},
      options:{provider:'options',model:'fallback'}}}}
    if (scenario==='aborted') controller.abort()
    const value = await definition.execute({},execution)
    const fallback = definition.output.render({},value)
    const result = {value:structuredClone(value),content:structuredClone(fallback),isError:scenario==='result-error'}
    if (scenario==='replaced-value') result.value.structuredContent.flag = true
    if (scenario==='boolean-number') result.value.structuredContent.flag = 0 as any
    if (scenario==='changed-content') result.content[0].text = 'changed'
    const second = {signal:controller.signal,agent:(execution as any).agent}
    if (scenario==='concurrent') await definition.execute({},second)
    const final = definition.finalizeContent(scenario==='foreign-execution' ? second : execution,result)
    const repeated = definition.finalizeContent(execution,{value,content:fallback,isError:false})
    const concurrent = scenario==='concurrent' ? definition.finalizeContent(second,{value,content:fallback,isError:false}) : undefined
    observations.push({kind:'rich',scenario,value,fallback,trace,...final===undefined ? {} : {final},
      ...repeated===undefined ? {} : {repeated},...concurrent===undefined ? {} : {concurrent}})
    for (const dispose of disposers.values()) dispose()
  }
  writeFileSync(process.env.MCP_TOOLS_OUTPUT!, JSON.stringify(observations,null,2)+'\n')
})
