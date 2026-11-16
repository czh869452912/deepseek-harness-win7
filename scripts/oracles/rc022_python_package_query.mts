import {readFileSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {viewProfilePackage}=await load('packages/boot/plugin-manager/src/operations.ts'),data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),dir=join(data.workspace,'source'),rows:any[]=[]
await mkdir(dir,{recursive:true});const config=join(dir,'npmrc');await writeFile(config,'')
const pnpm=join(process.argv[2]!,'apps/desktop/node_modules/pnpm/bin/pnpm.mjs')
for(const item of data.cases){
 const options:any={command:process.execPath,args:['--expose-internals',pnpm],fields:item.fields??data.fields,registry:data.registry,timeoutMs:5000,env:{NPM_CONFIG_USERCONFIG:config,LOCALAPPDATA:join(dir,'appdata'),APPDATA:join(dir,'appdata'),XDG_CACHE_HOME:join(dir,'cache'),NO_PROXY:'127.0.0.1,localhost'}}
 const observed=await viewProfilePackage(dir,item.spec,options)
 let result:any
 if(observed.exitCode===0)result=observed.stdout.trim()?JSON.parse(observed.stdout):{}
 else{const error=JSON.parse(observed.stdout||'{}');result={error:error.error?.code??'unclassified'};if(result.error==='unclassified')throw new Error(JSON.stringify(observed))}
 rows.push({name:item.name,result})
}
console.log(JSON.stringify(rows))
