import {createHmac,createHash} from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {BrowserAuth}=await load('packages/client/connection/src/browser-auth.ts'),NOW=1800000000000,original=Date.now,rows:any[]=[],secret=Buffer.from(Array.from({length:32},(_,i)=>i))
function response(){const state:any={status:null,headers:{},body:''};return {state,value:{writeHead(status:any,headers:any){state.status=status;state.headers=headers??{}},end(body:any){state.body=body??''}}}}
Date.now=()=>NOW
try{const auth=new BrowserAuth({},secret,1),token=new URL(auth.authenticatedUrl('http://localhost')).searchParams.get('token')
 for(const secure of [false,true]){const host=secure?'LOCALHOST:443':'LOCALHOST:80',published:any[]=[],cookies:any={}
  for(const kind of ['browser','api','answer']){const request={method:'GET',headers:{host},url:(kind==='browser'?'/?token=':'/connect?token=')+token+(kind==='answer'?'&interactions=answer':'')},res=response()
   if(kind==='browser')auth.authorizeIndex(request,res.value,secure);else auth.authorizeConnect(request,res.value,secure,(interactions:any)=>{published.push(interactions);return 'operator-id'})
   const cookie=res.state.headers['set-cookie'].split(';')[0];cookies[kind]=cookie
   const facts=[false,true].map(mode=>{const req={headers:{host,cookie}};return {secure:mode,browser:auth.isAuthenticated(req,mode),api:auth.authenticateApi(req,mode)??null}})
   rows.push({name:kind,secure,response:res.state,facts})
  }
  for(const query of ['bad','duplicate','none','invalid-interaction','duplicate-interaction','wrong-path','post','head','cookie-cleanup','api-index']){let raw='/connect?token='+token
   if(query==='bad')raw='/connect?token=bad';if(query==='duplicate')raw+='&token='+token;if(query==='none')raw='/connect';if(query==='invalid-interaction')raw+='&interactions=other';if(query==='duplicate-interaction')raw+='&interactions=none&interactions=answer';if(query==='wrong-path')raw=raw.replace('/connect','/nested/connect');if(query==='cookie-cleanup')raw='/?token=bad';if(query==='api-index')raw='/'
   const request={method:query==='post'?'POST':query==='head'?'HEAD':'GET',headers:{host,cookie:query==='api-index'?cookies.api:cookies.browser},url:raw},res=response();let allowed:any=null
   if(['cookie-cleanup','api-index'].includes(query))allowed=auth.authorizeIndex(request,res.value,secure);else auth.authorizeConnect(request,res.value,secure,(interactions:any)=>{published.push(interactions);return 'operator-id'})
   rows.push({name:query,secure,response:res.state,allowed})
  }
  rows.push({name:'published',secure,values:published})
 }
 for(const [name,changes] of Object.entries({valid:{},expired:{expiresAt:NOW},future:{issuedAt:NOW+1},reversed:{expiresAt:NOW-1},'too-long':{expiresAt:NOW+86400001},'wrong-authority':{authority:'evil'},'empty-id':{id:''},'bad-id':{id:4},'bad-version':{version:3},fractional:{issuedAt:NOW-0.5},boolean:{issuedAt:true},extra:{extra:'ignored'}})){
  const payload:any={version:2,authority:'localhost',id:'operator-id',issuedAt:NOW-1,expiresAt:NOW+10,...changes},body=Buffer.from(JSON.stringify(payload)).toString('base64url'),cookie='dsh-auth-'+createHash('sha256').update('localhost').digest('base64url')+'=v'+payload.version+'.'+body+'.'+createHmac('sha256',secret).update(body).digest('base64url'),request={headers:{host:'localhost',cookie}}
  rows.push({name,browser:auth.isAuthenticated(request),api:auth.authenticateApi(request)??null})
 }
 for(const base of ['http://localhost/mount/?x=1#hash','https://localhost/path?token=old&x=a+b&token=second'])rows.push({name:'url',value:auth.authenticatedUrl(base).replace(token,'TOKEN')})
}finally{Date.now=original}
process.stdout.write(JSON.stringify(rows))
