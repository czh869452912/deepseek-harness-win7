import {readFileSync} from 'node:fs'
import {mkdir,readFile,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {writePluginEnabled}=await load('packages/boot/plugin-manager/src/patch.ts'),{loadOptionalPatches}=await load('packages/boot/app-boot/src/index.ts')
const input=JSON.parse(readFileSync(process.argv[3]!,'utf8')),output:any[]=[]
for(const sample of input.cases){
 const home=join(input.workspace,'source',sample.name),dir=join(home,'profile'),bundle=join(dir,'node_modules/bundle');await mkdir(bundle,{recursive:true})
 const write=(path:string,value:any)=>writeFile(path,JSON.stringify(value)),filename=join(dir,'cordis.patch.yml')
 await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dsh:{profile:{bundles:['bundle']}}});await write(join(bundle,'package.json'),{name:'bundle',version:'1.0.0',dsh:{bundle:{patch:'cordis.patch.yml'}}});await write(join(bundle,'cordis.patch.yml'),[{insert:sample.rows}])
 if(sample.text!==null)await writeFile(filename,sample.text)
 await write(join(home,'cordis.patch.yml'),[{id:'tool',disabled:true}])
 const profile={name:'test',dir,patchPath:filename,installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['bundle'],overlays:[{id:'tool',disabled:true}],telemetryDisabledEnv:undefined}
 const read=()=>readFile(filename,'utf8').catch((error:any)=>{if(error.code==='ENOENT')return null;throw error}),steps:any[]=[]
 for(const enabled of sample.actions){
  const before=await read()
  try{const changed=await writePluginEnabled(profile,'tool','package',enabled),text=await read();steps.push({changed,patches:loadOptionalPatches('test',filename)??null,comments:text?.match(/#[^\n]*/g)??[],expression:text?.includes('!!js process.platform')??false,unchanged:before===text})}
  catch{steps.push({refused:true,unchanged:before===await read()})}
 }
 output.push({name:sample.name,steps})
}
console.log(JSON.stringify(output))
