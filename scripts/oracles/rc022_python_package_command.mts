import {readFileSync} from 'node:fs'
import {mkdir,writeFile} from 'node:fs/promises'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const {boot,readProfilePatches}=await load('packages/boot/app-boot/src/index.ts'),{default:Manager}=await load('packages/boot/plugin-manager/src/index.ts'),data=JSON.parse(readFileSync(process.argv[3]!,'utf8')),home=join(data.workspace,'source'),dir=join(home,'profile')
async function write(path:string,value:any){await mkdir(join(path,'..'),{recursive:true});await writeFile(path,JSON.stringify(value))}
await write(join(home,'package.json'),{name:'installation'});await write(join(dir,'package.json'),{name:'profile',dependencies:{fresh:'1.0.0'},dsh:{profile:{bundles:['core']}}})
for(const name of ['core','fresh'])await write(join(dir,'node_modules',name,'package.json'),{name,version:'1.0.0',dsh:{bundle:{patch:'patch.yml'}}})
await write(join(dir,'node_modules/core/patch.yml'),[{insert:[{id:'manager',name:'cordis:manager',config:{lockWaitMs:0,fallbackRegistries:[]}}]}]);await write(join(dir,'node_modules/fresh/patch.yml'),[]);await write(join(dir,'cordis.yml'),[]);await write(join(dir,'cordis.patch.yml'),[])
const blank=join(dir,'npmrc');await writeFile(blank,'')
const profile:any={name:'test',dir,patchPath:join(dir,'cordis.patch.yml'),installAnchor:join(home,'package.json'),cwd:home,home,startedBundles:['core'],overlays:[],packageManager:{...data.command,env:{PATH:'',NPM_CONFIG_USERCONFIG:blank,npm_config_registry:data.registry,NO_PROXY:'127.0.0.1,localhost'}}}
const ctx=await boot('test',join(dir,'cordis.yml'),readProfilePatches('test',profile),(ctx:any)=>{ctx.provide('profileContext',profile);ctx.loader.builtins.manager=Manager})
try{
 const manager=ctx.pluginManager,rows:any[]=[{name:'registries',result:await manager.registries()}]
 for(const [name,spec] of [['inspect','timed'],['scope','@scope/pkg'],['alias','alias@npm:@scope/pkg@^1.0.0'],['known','fresh'],['missing','timed@8.0.0']])rows.push({name,result:await manager.inspect(spec)})
 rows.push({name:'versions',result:await manager.listVersions('fresh')})
 function normalize(value:any):any{if(Array.isArray(value))return value.map(normalize);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,normalize(item)]));return typeof value==='string'?value.split(data.registry).join('<registry>/'):value}
 console.log(JSON.stringify(normalize(rows)))
}finally{await ctx.fiber.dispose()}
