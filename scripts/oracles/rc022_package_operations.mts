import {existsSync,readFileSync} from 'node:fs'
import {mkdir,writeFile,readFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {runProfilePnpm}=await load('packages/boot/plugin-manager/src/operations.ts'),data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
async function write(path:string,value:any){await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
function normalize(value:any,dir:string):any{
 if(Array.isArray(value))return value.map(item=>normalize(item,dir))
 if(value!==null&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item,dir)]))
 return typeof value==='string'?value.split(dir).join('<profile>'):value
}
for(const item of data.cases){
 const home=join(data.workspace,'source',item.name),dir=join(home,'profile');await mkdir(dir,{recursive:true})
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),item.before);await write(join(dir,'operation.json'),item)
 for(const [name,manifest] of Object.entries(item.beforePackages??{})){await write(join(dir,'node_modules',name,'package.json'),manifest);await write(join(dir,'node_modules',name,'patch.yml'),[])}
 if(!item.noLock)await writeFile(join(dir,'pnpm-lock.yaml'),'original\r\n')
 if(item.record!==undefined){await mkdir(join(dir,'.plugin-manager'));await writeFile(join(dir,'.plugin-manager/run.json'),item.record)}
 if(item.corruptProfile)await writeFile(join(dir,'package.json'),'{broken')
 const script=join(dir,'package.py'),output:any[]=[];await writeFile(script,data.program)
 const result=await runProfilePnpm({profile:'test',dir,cwd:home,home,installAnchor:join(home,'package.json')},item.args,{command:data.python,args:[script],execution:'service',outputBytes:16384,idleTimeoutMs:5000,onOutput:(text:string,kind:string)=>output.push({text,kind}),...item.options})
 const log=await readFile(result.logPath,'utf8');delete result.logPath
 let runs:any[]=[];try{runs=(await readFile(join(dir,'runs.jsonl'),'utf8')).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line))}catch{}
 const manifest=item.corruptProfile?'untouched-corrupt':JSON.parse(await readFile(join(dir,'package.json'),'utf8')),lock=existsSync(join(dir,'pnpm-lock.yaml'))?await readFile(join(dir,'pnpm-lock.yaml'),'utf8'):null,streams=Object.fromEntries(['stdout','stderr'].map(kind=>[kind,output.filter(row=>row.kind===kind).map(row=>row.text).join('')]))
 rows.push(normalize({name:item.name,result,log,streams,runs,manifest,lock,recordRemoved:!existsSync(join(dir,'.plugin-manager/run.json'))},dir))
}
console.log(JSON.stringify(rows))
