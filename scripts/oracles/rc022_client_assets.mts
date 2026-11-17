import {readFileSync} from 'node:fs'
import {pathToFileURL} from 'node:url'
import {createRequire} from 'node:module'
import {createHash} from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{ClientModuleRegistry}=await load('packages/client/modules/src/index.ts')
const {workspace}=JSON.parse(readFileSync(process.argv[3]!,'utf8')),name='@fixture/assets',ctx=new Context(),rows:any[]=[]
ctx.provide('loader',{entries:()=>[name,'fixture-no-assets'].map(name=>({options:{name},fiber:{},disabled:false,parent:{tree:{ctx:{baseUrl:pathToFileURL(workspace).href+'/'}}}})).values(),internal:{version:'v2',resolveSync:(base:string,input:any)=>({url:pathToFileURL(createRequire(base).resolve(input.specifier)).href})}})
const cases:any[]=[['svg','icon.svg'],['png','photo.png'],['webp','nested/a%20b.webp'],['special',"whale%282x%29%21%27.png"],
 ['large','large.png'],['head','icon.svg','HEAD'],['not-modified','icon.svg','GET','"icon.svg"'],
 ['wrong-etag','icon.svg','GET','"photo.png"'],['weak-etag','icon.svg','GET','W/"icon.svg"'],
 ['post','icon.svg','POST'],['private','private/hidden.png'],['missing','missing.png'],['directory','folder.png'],
 ['unsupported','notes.txt'],['empty',''],['escape','../../secret.png'],['encoded-escape','%2e%2e/%2e%2e/secret.png'],
 ['encoded-slashes','..%2f..%2fsecret.png'],['bad-percent','photo%zz.png'],['bad-utf8','%ff.png'],
 ['literal-percent','100%25.png'],['fragment','a%23b.png']]
try{
 const registry=new ClientModuleRegistry(ctx)
 const request=async(stage:string,path:string,method='GET',tag?:string)=>{
  const result=await registry.fetchBundle(new Request('http://x'+path,{method,headers:tag?{'If-None-Match':tag}:{}}))
  const body=Buffer.from(await result.arrayBuffer())
  rows.push({stage,status:result.status,headers:Object.fromEntries(result.headers),length:body.length,sha256:createHash('sha256').update(body).digest('hex')})
 }
 for(const [stage,path,method,tag] of cases)await request(stage,`/plugins/${name}/assets/${path}`,method,tag)
 await request('no-export','/plugins/fixture-no-assets/assets/photo.png');await request('inactive','/plugins/fixture-inactive/assets/photo.png')
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
