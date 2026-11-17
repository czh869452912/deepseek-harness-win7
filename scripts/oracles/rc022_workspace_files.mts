import fs from 'node:fs/promises'
import {join,dirname} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const runtime=await load('packages/skill/tool-workspace-dependencies/src/index.ts')
const input=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
for(const scenario of input.scenarios){
 const base=join(input.directory,scenario),source=join(base,'source'),root=join(base,'home','runtime'),outside=join(base,'outside')
 await fs.mkdir(source,{recursive:true});await fs.mkdir(outside);await fs.writeFile(join(outside,'keep'),'outside')
 const manifest:any={desktopVersion:'fixture',platform:process.platform,arch:process.arch,python:'3.8.10',node:'16.20.2',pnpm:'8.15.9',pythonPackages:{NumPy:'1.24.4',Pillow:'10.4.0'}}
 const paths=runtime.workspaceDependencyPaths(source,manifest)
 for(const key of ['python','node','pnpm']){await fs.mkdir(dirname(paths[key]),{recursive:true});await fs.writeFile(paths[key],'interpreter')}
 for(const key of ['pythonPackages','nodePackages'])await fs.mkdir(paths[key],{recursive:true})
 const write=async(value=manifest)=>fs.writeFile(join(source,'runtime.json'),JSON.stringify(value));await write()
 const link=async(path:string,target:string)=>{await fs.mkdir(dirname(path),{recursive:true});await fs.symlink(target,path,process.platform==='win32'?'junction':'dir')}
 let error:any=null,value:any=null
 try{
  if(['reuse','digest','recover','incomplete','bad-installed-json','package-order','unknown-fields','manifest-link','reuse-wrong-entry','recovery-incomplete','old-previous'].includes(scenario)){
   await runtime.installPrimaryRuntime(source,root);await fs.writeFile(join(root,'user-package'),'user')
  }
  if(['recover','recovery-incomplete'].includes(scenario))await fs.rename(root,root+'.previous')
  if(['digest','incomplete','recovery-incomplete','old-previous'].includes(scenario)){manifest.payloadDigest='a'.repeat(64);await write()}
  if(['incomplete','recovery-incomplete'].includes(scenario))await fs.unlink(paths.python)
  if(scenario==='wrong-python'){await fs.unlink(paths.python);await fs.mkdir(paths.python)}
  if(scenario==='wrong-packages'){await fs.rmdir(paths.pythonPackages);await fs.writeFile(paths.pythonPackages,'wrong')}
  if(scenario==='bad-arch'){manifest.arch=manifest.arch==='x64'?'arm64':'x64';await write()}
  if(scenario==='bad-json')await fs.writeFile(join(source,'runtime.json'),'{')
  if(scenario==='bad-installed-json')await fs.writeFile(join(root,'runtime.json'),'{')
  if(scenario==='package-order'){manifest.pythonPackages={Pillow:'10.4.0',NumPy:'1.24.4'};await write()}
  if(scenario==='unknown-fields')await write({...manifest,unknown:true})
  if(['root-link','previous-link'].includes(scenario))await link(scenario==='root-link'?root:root+'.previous',outside)
  if(scenario==='manifest-link'){await fs.unlink(join(root,'runtime.json'));await link(join(root,'runtime.json'),outside)}
  if(scenario==='payload-link')await link(join(source,'extra'),outside)
  if(scenario==='reuse-wrong-entry'){const installed=runtime.workspaceDependencyPaths(root,manifest).python;await fs.unlink(installed);await fs.mkdir(installed)}
  if(scenario==='old-previous'){await fs.mkdir(root+'.previous');await fs.writeFile(join(root+'.previous','stale'),'old')}
  value=await(scenario==='resolve'?runtime.resolvePrimaryRuntime(source):runtime.installPrimaryRuntime(source,root))
  value=Object.fromEntries(Object.entries(value).map(([k,v])=>[k,typeof v==='string'?v.replaceAll(base,'<base>').replaceAll('\\','/'):v]))
 }catch(caught:any){await fs.writeFile(join(base,'failure.txt'),caught.stack);error=caught.code?{code:caught.code}:caught instanceof SyntaxError?{code:'JSON_PARSE'}:{message:caught.message.replaceAll(base,'<base>').replaceAll('\\','/').replace(/\.primary-runtime-[^/]+/g,'.primary-runtime-<staging>')}}
 async function snapshot(path:string):Promise<any>{
  let entry;try{entry=await fs.lstat(path)}catch(e:any){if(e.code==='ENOENT')return null;throw e}
  if(entry.isSymbolicLink())return 'link'
  if(entry.isFile())return fs.readFile(path,'utf8')
  const value:any={};for(const child of(await fs.readdir(path)).sort())value[child]=await snapshot(join(path,child));return value
 }
 const row:any={scenario,error,value,root:await snapshot(root),previous:await snapshot(root+'.previous'),outside:await snapshot(outside),staging:(await fs.readdir(dirname(root)).catch(()=>[])).filter(x=>x.startsWith('.primary-runtime-')).sort()}
 for(const key of ['root','previous'])if(typeof row[key]?.['runtime.json']==='string'){try{row[key]['runtime.json']=JSON.parse(row[key]['runtime.json'])}catch{}}
 rows.push(row)
}
console.log(JSON.stringify(rows))
