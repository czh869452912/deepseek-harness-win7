import {it,expect} from 'vitest'
import {writeFile} from 'node:fs/promises'
import {createServer} from 'node:http'
import {DeepSeekAdapter,resolveAdapterOptions} from '../../reference/packages/llm/llm-deepseek/src/index.ts'

const fixtures = [
  ...['same','cross'].flatMap(origin => [301,302,303,307,308].map(status => ({name:origin+'-'+status,origin,status,hops:1}))),
  {name:'same-307-twenty',origin:'same',status:307,hops:20},
  {name:'same-307-twenty-one',origin:'same',status:307,hops:21},
  {name:'same-307-loop',origin:'same',status:307,hops:30,loop:true},
  {name:'cross-back-307',origin:'cross-back',status:307,hops:2},
  {name:'rewrite-then-preserve',origin:'same',status:302,hops:2,second:307},
  ...['same','cross'].flatMap(origin => [302,307].map(status => ({name:'raw-'+origin+'-POST-'+status,origin,status,hops:1,method:'POST'}))),
  ...[301,303,307].map(status=>({name:'raw-same-PUT-'+status,origin:'same',status,hops:1,method:'PUT'})),
  {name:'raw-same-HEAD-303',origin:'same',status:303,hops:1,method:'HEAD'},
  {name:'raw-same-credentials',origin:'same',status:307,hops:1,method:'POST',credentials:true},
  {name:'raw-cross-credentials',origin:'cross',status:307,hops:1,method:'POST',credentials:true},
  {name:'raw-unsupported-protocol',origin:'same',status:307,hops:1,method:'POST',unsupported:true},
  {name:'raw-relative-fragment',origin:'same',status:307,hops:1,method:'POST',relative:true},
  {name:'raw-abort-before-follow',origin:'same',status:307,hops:1,method:'POST',abort:true},
  {name:'raw-stalled-redirect-body',origin:'same',status:307,hops:1,method:'POST',stalled:true},
]

it('records actual adapter redirects and request ownership',async () => {
  const rows:any[]=[]
  for (const fixture of fixtures) {
    const requests:any[]=[], servers:any[]=[], ports:number[]=[]
    const controller=new AbortController()
    for (const origin of [0,1]) {
      const server=createServer(async (request,response) => {
        const chunks=[]
        for await (const chunk of request) chunks.push(chunk)
        const raw=Buffer.concat(chunks).toString('utf8'), headers:any={}
        for (const name of ['authorization','content-type','x-deepseek-harness-user-id','x-deepseek-harness-session-id','x-deepseek-harness-compact',
          ...fixture.method ? ['proxy-authorization','cookie','content-encoding','content-language','content-location'] : []]) {
          if (request.headers[name] !== undefined) headers[name]=request.headers[name]
        }
        requests.push({origin,method:request.method,path:request.url,headers,body:raw ? JSON.parse(raw) : null})
        if (fixture.method) requests.at(-1).hostOverride=request.headers.host==='fixture-host'
        if (requests.length <= fixture.hops) {
          const destination=fixture.origin==='cross' ? 1 : fixture.origin==='cross-back' ? (requests.length===1 ? 1 : 0) : 0
          const target=fixture.loop ? '/chat/completions' : '/redirect/'+requests.length
          const location=fixture.unsupported ? 'ftp://127.0.0.1:1/resource' : fixture.relative ? '../redirect/one?query=hello world#fragment'
            : `http://${fixture.credentials ? 'fixture:credential@' : ''}127.0.0.1:${ports[destination]}${target}`
          if (fixture.abort) controller.abort()
          response.writeHead(requests.length===2 && fixture.second ? fixture.second : fixture.status,
            {Location:location,...fixture.stalled ? {'Content-Length':'999999'} : {}})
          if (fixture.stalled) response.flushHeaders()
          else response.end()
        } else {
          response.writeHead(200,{'Content-Type':'text/event-stream'})
          response.end('data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        }
      })
      await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve))
      ports.push((server.address() as any).port)
      servers.push(server)
    }
    const adapter=new DeepSeekAdapter({options:()=>resolveAdapterOptions({baseURL:`http://127.0.0.1:${ports[0]}`,streamIdleTimeoutMs:3000}),
      resolveApiKey:async ()=>'fixture-key',resolveUserId:()=> 'fixture-user' as any,
      prepareExtensions:async ()=>({fields:{},accept:async ()=>{}})})
    const row:any={name:fixture.name,requests,chunks:[]}
    try {
      if (fixture.method) {
        const response=await fetch(`http://127.0.0.1:${ports[0]}/chat/completions`,{method:fixture.method,signal:controller.signal,
          headers:{authorization:'Bearer fixture-key','proxy-authorization':'fixture-proxy',cookie:'fixture-cookie',host:'fixture-host',
            'content-type':'application/json','content-encoding':'identity','content-language':'en','content-location':'fixture-location'},
          ...fixture.method==='HEAD' ? {} : {body:'{"probe":1}'}})
        row.status=response.status
        row.text=await response.text()
      } else {
        for await (const chunk of adapter.stream({provider:'deepseek-official',model:'model',
          messages:[{role:'user',content:[{type:'text',text:'hello'}]}],sessionId:'fixture-session' as any,purpose:'compaction'})) row.chunks.push(chunk)
      }
    } catch (error:any) {
      row.error={code:fixture.method ? (controller.signal.aborted ? 'ABORTED' : 'TRANSPORT') : error.code,status:error.failure?.status ?? null}
    } finally {
      for (const server of servers) {
        server.closeAllConnections()
        await new Promise<void>(resolve=>server.close(()=>resolve()))
      }
    }
    expect(requests.length).toBe(!fixture.method ? (fixture.hops <= 20 ? fixture.hops + 1 : 21)
      : fixture.credentials || fixture.unsupported || fixture.abort ? 1 : 2)
    rows.push(row)
  }
  await writeFile(process.env.HTTP_REDIRECT_OUTPUT!,JSON.stringify(rows,null,2)+'\n','utf8')
},15000)
