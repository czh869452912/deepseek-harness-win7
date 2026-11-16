import fs from 'node:fs'
import http from 'node:http'
import {createHash} from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const {default:Authorization}=await load('packages/credentials/authorization/src/index.ts')
const {DeepSeekAccount}=await load('packages/credentials/deepseek-account/src/index.ts')
const {default:WebServer}=await load('packages/host/webserver/src/index.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),rows:any[]=[],key='deepseek-account-platform/default',deviceKey='deepseek-account-platform/device',log=console.error
function browser(origin:string,target:string,method='GET'):Promise<any>{
 return new Promise((resolve,reject)=>{
  const request=http.request(origin+target,{method,headers:{connection:'close'}},res=>{
   const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString('utf8')}));res.on('error',reject)
  });request.on('error',reject);request.end()
 })
}
function normalizedCallback(value:any,origin:string){
 if(value===null)return null
 const headers:any={};for(const [key,entry] of Object.entries(value.headers))if(['location','cache-control','content-type','content-security-policy','referrer-policy'].includes(key))headers[key]=(entry as string).replace(origin,'<platform>')
 let body=value.body
 if(headers['content-security-policy']){
  const csp=headers['content-security-policy'],nonce=/nonce-([^']+)/.exec(csp)![1]!
  if(!/^[A-Za-z0-9_-]{22}$/.test(nonce)||!body.includes(`nonce="${nonce}"`))throw new Error('nonce binding failed')
  headers['content-security-policy']=csp.replace(nonce,'<nonce>');body=body.replaceAll(nonce,'<nonce>')
 }
 return{status:value.status,headers,body}
}
try{
 for(const mode of input){
  const ctx=new Context(),records:any={},hits:any[]=[],logs:any[]=[],verification:any[]=[],init:any={}
  const commitEntered=Promise.withResolvers<void>(),commitGate=Promise.withResolvers<void>();let origin='',result:any,callback:any=null
  const exchangeEntered=Promise.withResolvers<void>(),exchangeGate=Promise.withResolvers<void>(),initGate=Promise.withResolvers<void>()
  if(mode==='invalid-device')records[deviceKey]={kind:'grant',payload:{id:'not-uuid'}}
  ctx.provide('credentials',{
   async readRecord(key:string){return records[key]},async describeRecord(key:string){return{configured:key in records}},
   async modifyRecord(key:string,mutate:any){const value=await mutate(records[key]);if(value!==undefined){if(key==='deepseek-account-platform/default'&&mode==='commit-cancel'){commitEntered.resolve();await commitGate.promise}records[key]=value;ctx.emit('credentials/record-updated',key)}return records[key]},
   async deleteRecord(key:string){if(key in records){delete records[key];ctx.emit('credentials/record-updated',key)}}
  })
  const server=http.createServer(async(req,res)=>{
   const chunks=[];for await(const chunk of req)chunks.push(chunk)
   const data=Buffer.concat(chunks).toString('utf8'),body=data?JSON.parse(data):null
   hits.push({path:req.url,method:req.method,token:req.headers['x-dsh-auth-token']??null,locale:req.headers['x-client-locale']??null,platform:req.headers['x-client-platform']??null,cookie:req.headers.cookie??null})
   let status=200,payload:any
   if(req.url!.endsWith('auth_init')){
    if(mode==='init-timeout')await initGate.promise
    Object.assign(init,body);payload={authorize_url:origin+(mode==='invalid-authorize-url'?'/wrong?private-secret':'/dsh/authorize?authorize_id=fixture'),authorize_id:'fixture',expires_in:600}
    if(mode==='invalid-init')payload.expires_in='private-secret'
    verification.push({method:body.code_challenge_method,locale:body.locale,source:body.login_source,stateLength:body.state.length,challengeLength:body.code_challenge.length,callbackMatches:body.redirect_uri===ctx.webServer.getOrigin()+'/oauth/callback'})
   }else if(req.url!.endsWith('auth_exchange')){
    exchangeEntered.resolve();if(['duplicate-callback','cancel-exchanging'].includes(mode))await exchangeGate.promise
    verification.push({pkce:createHash('sha256').update(body.code_verifier).digest('base64url')===init.code_challenge,code:body.code,redirectMatches:body.redirect_uri===init.redirect_uri,deviceValid:/^[0-9a-f-]{36}$/.test(body.device_id),deviceModel:body.device_model,osVersion:body.os_version})
    payload={token:'fixture-token',authorized_url:origin+(mode==='invalid-completion-url'?'/wrong':'/dsh/authorized?x=a%2Fb&login_source=old&login_source=duplicate&v=~#'),user:{id:'user-id',email:'masked',token:'must-discard'}}
    if(mode==='invalid-user')payload.user={email:7}
    if(mode==='invalid-exchange')payload.token='invalid token'
    if(mode.startsWith('exchange-failure'))status=503
   }else if(req.url!.endsWith('auth_cancel')){
    verification.push({cancelId:body.authorize_id,verifierMatches:createHash('sha256').update(body.code_verifier).digest('base64url')===init.code_challenge});payload=null
   }else payload={id:'fallback-user',email:'masked'}
   res.statusCode=status;res.end(JSON.stringify({code:0,data:{biz_code:0,biz_data:payload}}))
  })
  await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${(server.address() as any).port}`
  console.error=(label:any,value:any)=>logs.push({label:String(label).replace('[deepseek-account] ',''),...value})
  const invalid:number[]=[]
  try{
   await ctx.plugin(WebServer,{host:'127.0.0.1',port:0});await ctx.plugin(Authorization)
   await ctx.plugin(DeepSeekAccount,{platformOrigin:origin,inferenceOrigin:origin,allowLoopbackHttp:true,desktopPlatform:null,requestHeaders:{cookie:'gate=fixture'},requestTimeoutMs:mode==='init-timeout'?100:3000,attemptTimeoutMs:mode==='expire-waiting'?300:3000})
   const account=ctx.deepseekAccount,client={version:'fixture/1',locale:mode==='exchange-failure-zh'?'zh':'en',timezoneOffsetSeconds:28800}
   const start=await account.startSignIn(client,ctx.webServer.getOrigin(),mode==='exchange-failure-desktop'?'desktop':'web')
   let state:any
   for(let attempt=0;attempt<1000;attempt++){state=await account.getState();if(state.attempt.phase!=='initializing')break;await new Promise(resolve=>setTimeout(resolve,2))}
   if(state.attempt.phase==='initializing')throw new Error('login did not initialize')
   const joined=state.attempt.phase==='waiting-browser'?await account.startSignIn({...client,locale:'other'},ctx.webServer.getOrigin(),'desktop'):null
   const joinSame=joined===null||joined.attempt.id===state.attempt.id
   if(state.attempt.phase==='waiting-browser'){
    const target='/oauth/callback?state='+encodeURIComponent(init.state)+'&code=fixture-code'
    if(mode==='invalid-callbacks'){
     for(const bad of [target+'&code=duplicate',target+'&state=duplicate','/oauth/callback?state=wrong&code=fixture-code',target.replace('fixture-code','')])invalid.push((await browser(ctx.webServer.getOrigin(),bad)).status)
     invalid.push((await browser(ctx.webServer.getOrigin(),target,'POST')).status)
    }
    if(mode==='cancel-waiting')await account.cancelSignIn(state.attempt.id)
    else if(mode!=='expire-waiting'){
     const pending=browser(ctx.webServer.getOrigin(),target)
     if(['duplicate-callback','cancel-exchanging'].includes(mode)){await exchangeEntered.promise;if(mode==='duplicate-callback')invalid.push((await browser(ctx.webServer.getOrigin(),target)).status);else await account.cancelSignIn(state.attempt.id);exchangeGate.resolve()}
     if(mode==='commit-cancel'){await commitEntered.promise;let complete=false;const cancel=account.cancelSignIn(state.attempt.id).then(value=>{complete=true;return value});await Promise.resolve();if(complete)throw new Error('commit cancellation did not wait');commitGate.resolve();await cancel}
     callback=await pending
    }
   }
   await (account as any).attempt.done
   const final=await account.getState(),phase=final.attempt.phase,selected:any={phase}
   if(final.attempt.errorCode!==undefined)selected.errorCode=final.attempt.errorCode
   if(final.attempt.authorizeUrl!==undefined)selected.authorizeUrl=final.attempt.authorizeUrl.replace(origin,'<platform>')
   const profile=phase==='succeeded'?await account.getProfile(client):null
   let stored=records[key]??null;if(stored!==null){if(stored.payload.issuer!==origin)throw new Error('issuer mismatch');stored={...stored,payload:{...stored.payload,issuer:'<platform>'}}}
   result={initialPhase:start.attempt.phase,joinSame,final:{status:final.status,attempt:selected},callback:normalizedCallback(callback,origin),invalid,stored,profile,
    routeGone:!(ctx.webServer as any).exact.has('/oauth/callback'),flowInFlight:ctx.authorization.describe(key).inFlight}
  }finally{commitGate.resolve();exchangeGate.resolve();initGate.resolve();await ctx.fiber.dispose();server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()))}
  rows.push({mode,result,hits,verification,diagnostics:logs})
 }
}finally{console.error=log}
process.stdout.write(JSON.stringify(rows))
