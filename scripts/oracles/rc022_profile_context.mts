import {mkdirSync,readFileSync,readdirSync,writeFileSync,unlinkSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {loadProfileDirectory,composeEntries}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile.ts')).href)
const {readProfilePatches}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile-context.ts')).href)
function pkg(path:string,name:string,fields:any={}){mkdirSync(path,{recursive:true});writeFileSync(join(path,'package.json'),JSON.stringify({name,version:'1.0.0',...fields}));return join(path,'package.json')}
function stage(directory:string,mode:string){
 const home=join(directory,'home'),active=join(home,'profiles/active'),installAnchor=pkg(join(directory,'installation'),'installation')
 pkg(active,'profile',{dependencies:{selected:'*'},dsh:{profile:{bundles:['selected']}}})
 const selected=join(active,'node_modules/selected');pkg(selected,'selected',{dependencies:{private:'*'},dsh:{bundle:{patch:'./patch.yml'}}});pkg(join(selected,'node_modules/private'),'private')
 const bundle=join(selected,'patch.yml');writeFileSync(bundle,JSON.stringify([{insert:[{id:'session-telemetry-otel',name:'telemetry',config:{value:'bundle'}}]}]))
 const canonical=join(active,'cordis.patch.yml');writeFileSync(canonical,JSON.stringify([{id:'session-telemetry-otel',config:{value:'initial-user'}}]))
 const initial=loadProfileDirectory('probe',active,installAnchor),custom=join(active,'custom.patch.yml');writeFileSync(custom,JSON.stringify([{id:'session-telemetry-otel',config:{value:'current-user'}}]))
 const homePatch=join(home,'cordis.patch.yml');writeFileSync(homePatch,JSON.stringify([{id:'session-telemetry-otel',disabled:true}]))
 if(mode.startsWith('edited-'))writeFileSync(bundle,JSON.stringify([{insert:[{id:'session-telemetry-otel',name:'telemetry',config:{value:'edited-bundle'}}]}]))
 if(mode==='invalid-canonical')writeFileSync(canonical,'{broken')
 if(mode==='invalid-user')writeFileSync(custom,'{broken')
 if(mode==='missing-user')unlinkSync(custom)
 if(mode==='missing-home')unlinkSync(homePatch)
 if(mode==='invalid-home')writeFileSync(homePatch,'{}')
 if(mode==='no-telemetry')writeFileSync(bundle,'[]')
 if(mode==='bundle-selection'){const manifest=join(active,'package.json'),value=JSON.parse(readFileSync(manifest,'utf8'));value.dsh.profile.bundles=[];writeFileSync(manifest,JSON.stringify(value))}
 return {context:{name:'active',dir:active,patchPath:custom,installAnchor,home,cwd:directory,startedBundles:['selected'],overlays:[{id:'session-telemetry-otel',disabled:false}],telemetryDisabledEnv:undefined},initial}
}
function files(path:string):Record<string,string>{
 const result:Record<string,string>={}
 for(const entry of readdirSync(path,{withFileTypes:true})){
  const file=join(path,entry.name)
  if(entry.isDirectory())Object.assign(result,files(file));else result[file]=readFileSync(file,'hex')
 }return result
}
const result:any[]=[]
for(const [index,spec] of JSON.parse(readFileSync(input,'utf8')).entries()){
 const directory=resolve(dirname(input),'files/source',String(index)),{context,initial}=stage(directory,spec.mode);context.telemetryDisabledEnv=spec.env
 const before=JSON.stringify(files(directory))
 try{
  const patches=readProfilePatches('probe',context,['initial','edited-initial'].includes(spec.mode)?initial:undefined)
  result.push({...spec,error:false,patches,entries:composeEntries([patches]),unchanged:before===JSON.stringify(files(directory))})
  // Store observations before checking detachment, without mutating the result.
  const detached=readProfilePatches('probe',context,['initial','edited-initial'].includes(spec.mode)?initial:undefined)
  detached.at(-1)!.disabled=true;if(context.overlays[0]!.disabled!==false)throw new Error('shared overlay')
 }catch{result.push({...spec,error:true,unchanged:before===JSON.stringify(files(directory))})}
}
process.stdout.write(JSON.stringify(result))
