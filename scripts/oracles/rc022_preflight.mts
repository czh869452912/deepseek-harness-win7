import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {boot,prepareProfileEntries,prepareProfilePatches}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const {Context}=await import(pathToFileURL(resolve(root,'vendor/cordis/src/index.ts')).href)
const modes=JSON.parse(readFileSync(input,'utf8')),result:any[]=[],rawWarnings:any[]=[]
function fixture(directory:string,mode:string,boot=false){
 mkdirSync(directory,{recursive:true})
 for(const name of ['allowed','denied','malformed','null']){
  const path=join(directory,'node_modules',name);mkdirSync(path,{recursive:true})
  const manifest:any={name,version:name==='denied'&&mode==='other-version'?'2.0.0':'1.0.0',type:'module',exports:'./index.mjs'}
  if(name==='denied')manifest.engines={dsh:'^99'}
  if(name==='malformed')manifest.peerDependencies=[]
  writeFileSync(join(path,'package.json'),JSON.stringify(name==='null'?null:manifest))
  writeFileSync(join(path,'index.mjs'),boot?`import {appendFileSync} from 'node:fs'; const record=v=>appendFileSync(${JSON.stringify(join(directory,'effects'))},v+${JSON.stringify(String.fromCharCode(10))});record('import:${name}');export function apply(){record('apply:${name}')}`:'throw new Error("must not import in preflight")')
 }
 const denied={id:'denied',name:'denied'},allowed={id:'allowed',name:'allowed'}
 let rows:any[]=[allowed,denied]
 if(['relative','absolute','url'].includes(mode)){
  const path=join(directory,'node_modules/denied/index.mjs');rows=[{id:'denied',name:{relative:'./node_modules/denied/index.mjs',absolute:path,url:pathToFileURL(path).href}[mode]}]
 }
 if(mode==='alias'){
  const alias=join(directory,'aliased');mkdirSync(alias)
  for(const name of readdirSync(join(directory,'node_modules/denied')))writeFileSync(join(alias,name),readFileSync(join(directory,'node_modules/denied',name)))
  writeFileSync(join(directory,'package.json'),JSON.stringify({imports:{'#denied':'./aliased/index.mjs'}}));rows=[{id:'alias',name:'#denied'}]
 }
 if(['group','disabled-group'].includes(mode)){rows=[{id:'group',name:'cordis:group',group:true,config:rows}];if(mode==='disabled-group')rows[0].disabled=true}
 if(mode==='denied-group')rows=[{id:'group',name:'denied',group:true,config:[allowed]}]
 if(['include','include-patched','initial','cycle','mapping','dynamic'].includes(mode)){
  const path=join(directory,'nested.yml'),config:any={path:pathToFileURL(path).href}
  let content:any=mode==='mapping'?{mapping:true}:[denied]
  if(mode==='cycle'){
   writeFileSync(join(directory,'inner.yml'),JSON.stringify([{id:'inner',name:'cordis:include',config:{path:pathToFileURL(path).href}}]))
   content=[{id:'outer',name:'cordis:include',config:{path:pathToFileURL(join(directory,'inner.yml')).href}}]
  }
  if(mode==='initial')config.initial=[denied];else writeFileSync(path,JSON.stringify(content))
  if(mode==='include-patched')config.patches=[{id:'denied',disabled:true}]
  if(mode==='dynamic')config.path='./dynamic.py'
  rows=[{id:'include-denied',name:'cordis:include',config},allowed]
 }
 if(mode==='missing')rows=[{id:'missing',name:'./missing.mjs'},{id:'builtin',name:'node:fs'}]
 if(['malformed','null'].includes(mode))rows=[allowed,{id:mode,name:mode}]
 if(mode==='disabled')rows=[{...denied,disabled:true}]
 if(mode==='service')rows=[{id:'virtual',name:'virtual-plugin'}]
 const grants:any=['exempt','other-version','other-runtime','bad-record'].includes(mode)?{'denied@1.0.0':[mode==='other-runtime'?'9.9.9':'0.2.2-rc.3']}:{}
 if(mode==='bad-record')grants['bad@*']=['0.2.2-rc.3']
 writeFileSync(join(directory,'compatibility.json'),JSON.stringify(grants));writeFileSync(join(directory,'cordis.yml'),'[]\n')
 return rows
}
function files(directory:string):Map<string,string>{
 const result=new Map<string,string>()
 for(const entry of readdirSync(directory,{withFileTypes:true})){
  const path=join(directory,entry.name)
  if(entry.isDirectory())for(const [key,value] of files(path))result.set(key,value)
  else result.set(path,readFileSync(path,'hex'))
 }
 return result
}
const normalize=(value:any,directory:string)=>JSON.parse(JSON.stringify(value).replaceAll(JSON.stringify(directory).slice(1,-1),'$ROOT').replaceAll(pathToFileURL(directory).href,'$URL'))
for(const mode of modes.modes){
 const directory=resolve(dirname(input),'files/source/rows',mode),rows=fixture(directory,mode),before=JSON.stringify(rows),original=files(directory)
 const ctx=new Context()
 if(mode!=='non-profile')ctx.provide('profileContext',{dir:directory})
 if(mode==='service')ctx.provide('pluginPackages',{packageOf(){return {manifestPath:join(directory,'node_modules/denied/package.json')}}})
 let warning='',error:any=null,output:any=null
 const write=process.stderr.write;process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 try{
  try{output=prepareProfileEntries(ctx,rows,mode==='no-base'?undefined:pathToFileURL(directory).href+'/')}catch(e){error=(e as Error).message}
  const patches=[{insert:rows}]
  if(mode==='non-profile'&&prepareProfilePatches(ctx,patches,pathToFileURL(directory).href+'/')!==patches)throw new Error('non-profile changed patches')
 }finally{process.stderr.write=write;await ctx.fiber.dispose()}
 result.push({mode,rows:normalize(output,directory),error,unchanged:before===JSON.stringify(rows)&&[...original].every(([path,data])=>readFileSync(path,'hex')===data),imported:existsSync(join(directory,'effects')),diagnostics:{denials:warning.split('disabling profile plugin').length-1,invalid:warning.includes('cannot be validated'),include:warning.includes('never rewritten'),record:warning.includes('record is ignored')}})
 rawWarnings.push({mode,warning})
}
for(const mode of modes.boot){
 const directory=resolve(dirname(input),'files/source/boot',mode),rows=fixture(directory,mode,true),original=files(directory)
 let warning='',ctx:any;const write=process.stderr.write;process.stderr.write=((chunk:any)=>{warning+=String(chunk);return true}) as any
 try{ctx=await boot('probe',join(directory,'cordis.yml'),[{insert:rows}],host=>{host.provide('profileContext',{dir:directory})})}finally{process.stderr.write=write}
 try{
  const effects=existsSync(join(directory,'effects'))?readFileSync(join(directory,'effects'),'utf8').trim().split('\n'):[]
  result.push({boot:mode,effects:Object.fromEntries(['allowed','denied'].map(name=>[name,effects.filter(value=>value.endsWith(':'+name))])),unchanged:[...original].every(([path,data])=>readFileSync(path,'hex')===data),denials:warning.split('disabling profile plugin').length-1})
  rawWarnings.push({boot:mode,warning,effects})
 }finally{await ctx.fiber.dispose()}
}
writeFileSync(resolve(dirname(input),'source-warnings.json'),JSON.stringify(rawWarnings))
process.stdout.write(JSON.stringify(result))
