import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {loadLayeredEnv}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/index.ts')).href)
const inherited={...process.env},result:any[]=[]
try {
 for(const [index,name] of JSON.parse(readFileSync(input,'utf8')).entries()) {
  for(const mode of ['home','project','same','inherited']) {
   const directory=resolve(dirname(input),'files/source',String(index),mode)
   const home=join(directory,'home'),project=mode==='same'?home:join(directory,'project')
   mkdirSync(home,{recursive:true});mkdirSync(project,{recursive:true})
   writeFileSync(join(mode==='project'?project:home,'.env'),name+'=route\n')
   if(mode!=='same')writeFileSync(join(mode==='project'?home:project,'.env'),'ORDINARY=checked\n')
   for(const key of Object.keys(process.env))delete process.env[key]
   process.env.DSH_HOME=home
   if(mode==='inherited')process.env[name]='inherited'
   let error:any=null,snapshot:any
   // A DSH_HOME value inherited from the process is also the directory resolver's input.
   // Keep the resolver fixed to the fixture for the DSH_HOME rejection cases.
   if(name==='DSH_HOME'&&mode==='inherited')process.env.DSH_HOME=home
   try{snapshot=loadLayeredEnv('probe',project)}catch(e){error=(e as Error).message.replaceAll(directory,'$ROOT')}
   const entry=snapshot?.get(name)??null
   if(entry?.path)entry.path=entry.path.replaceAll(directory,'$ROOT')
   result.push({name,mode,error,value:name==='DSH_HOME'?process.env[name]?.replaceAll(directory,'$ROOT'):process.env[name]??null,ordinary:process.env.ORDINARY??null,entry})
  }
 }
} finally {
 for(const key of Object.keys(process.env))delete process.env[key]
 Object.assign(process.env,inherited)
}
process.stdout.write(JSON.stringify(result))
