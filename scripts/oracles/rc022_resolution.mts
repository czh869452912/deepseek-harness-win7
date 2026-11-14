import {existsSync,mkdirSync,readFileSync,readdirSync,symlinkSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!
const {createRuntimeResolution}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/src/profile.ts')).href)
const result:any[]=[]
function pkg(path:string,name:string,version='1.0.0',fields:any={}){mkdirSync(path,{recursive:true});const anchor=join(path,'package.json');writeFileSync(anchor,JSON.stringify({name,version,...fields}));return anchor}
function fixture(directory:string,mode:string){
 const home=join(directory,'home'),anchor=pkg(join(directory,'installation'),'installation','1.0.0',{dependencies:{core:'*',uninstalled:'*'},peerDependencies:{peer:'*'}})
 pkg(join(dirname(anchor),'node_modules/core'),'core','1.0.0',{dependencies:{shared:'*'},optionalDependencies:{extra:'*'}})
 for(const name of ['peer','shared','extra'])pkg(join(dirname(anchor),'node_modules',name),name)
 if(['invalid','skipped-invalid'].includes(mode))writeFileSync(join(dirname(anchor),'node_modules/core/package.json'),'{')
 const dir=join(home,'profiles/active');let layers:any[]=[]
 if(!['installation','refresh-installation'].includes(mode)){
  if(mode!=='synthetic')pkg(dir,'profile','1.0.0',{dependencies:{selected:'*',direct:'*'},peerDependencies:{direct:'*'},optionalDependencies:{optional:'*'},dsh:{profile:{bundles:['selected']}}});else mkdirSync(dir,{recursive:true})
  const selected=join(dir,'node_modules/selected');pkg(selected,'selected','1.0.0',{dependencies:{private:'*',shared:'*'},dsh:{bundle:{patch:'./patch.yml'}}});writeFileSync(join(selected,'patch.yml'),'[]')
  pkg(join(selected,'node_modules/private'),'private','1.0.0',{dependencies:{grandchild:'*'}});pkg(join(selected,'node_modules/shared'),'shared','99.0.0');pkg(join(selected,'node_modules/grandchild'),'grandchild')
  for(const name of ['direct','optional'])pkg(join(dir,'node_modules',name),name)
  const second=join(directory,'second');pkg(second,'second','1.0.0',{dependencies:{private:'*','second-only':'*'}});pkg(join(second,'node_modules/private'),'private','99.0.0');pkg(join(second,'node_modules/second-only'),'second-only')
  layers=[{packageName:'selected',packageDir:selected,patchPaths:[],patches:[]},{packageName:'second',packageDir:second,patchPaths:[],patches:[]}]
  if(mode==='other-profile')layers.reverse()
  if(mode==='optional')layers=[]
 }
 if(mode==='linked'){
  const external=join(directory,'external');pkg(external,'external');const internal=join(dir,'inside'),sibling=join(home,'profiles/sibling');mkdirSync(internal);mkdirSync(sibling)
  for(const [name,target] of [['linked',external],['inside',internal],['sibling',sibling],['dangling',join(directory,'missing')]])symlinkSync(target!,join(dir,'node_modules',name!),process.platform==='win32'?'junction':'dir')
 }
 return {installAnchor:anchor,home,profile:['installation','refresh-installation'].includes(mode)?undefined:{name:'active',dir,layers,skippedBundles:mode==='skipped-invalid'?[{packageName:'core',reason:'invalid'}]:[]}}
}
function files(directory:string){
 const result:Record<string,string>={}
 for(const entry of readdirSync(directory,{withFileTypes:true})){
  const path=join(directory,entry.name)
  if(entry.isSymbolicLink())continue
  if(entry.isDirectory())Object.assign(result,files(path));else result[path]=readFileSync(path,'hex')
 }
 return result
}
const table=(value:any)=>({profilesDir:value.profilesDir,profileDir:value.profileDir??null,localPackageNames:value.localPackageNames,entries:value.entries.map((row:any)=>({...row,version:row.version??null})),linkedRoots:value.linkedRoots})
for(const mode of JSON.parse(readFileSync(input,'utf8'))){
 const directory=resolve(dirname(input),'files/source',mode),options=fixture(directory,mode),before=JSON.stringify(files(directory));let resolution:any
 try{resolution=await createRuntimeResolution(options)}catch{result.push({mode,error:true,unchanged:before===JSON.stringify(files(directory))});continue}
 const row:any={mode,error:false,unchanged:before===JSON.stringify(files(directory)),table:table(resolution)}
 if(mode.startsWith('refresh-')){
  const old=JSON.stringify(table(resolution))
  if(mode==='refresh-installation')pkg(join(directory,'installation/node_modules/uninstalled'),'uninstalled')
  else{const selected=join(options.profile!.dir,'node_modules/selected'),manifest=JSON.parse(readFileSync(join(selected,'package.json'),'utf8'));manifest.dependencies['new-private']='*';writeFileSync(join(selected,'package.json'),JSON.stringify(manifest));pkg(join(selected,'node_modules/new-private'),'new-private')}
  row.successor=table(await resolution.computeLatestResolution());row.old_unchanged=old===JSON.stringify(table(resolution))
 }
 result.push(JSON.parse(JSON.stringify(row).replaceAll(JSON.stringify(directory).slice(1,-1),'$ROOT')))
}
process.stdout.write(JSON.stringify(result))
