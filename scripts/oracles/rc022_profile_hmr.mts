import{mkdirSync,readFileSync,writeFileSync}from'node:fs'
import{dirname,join,resolve}from'node:path'
import{pathToFileURL}from'node:url'
const root=process.argv[2]!,directory=resolve(dirname(process.argv[3]!),'files/source')
const {initProfile,loadProfileDirectory,loadProfile,loadOverlayPatches,composeEntries}=await import(pathToFileURL(resolve(root,'packages/boot/app-boot/lib/index.js')).href)
const {PROFILE_TEMPLATES}=await import(pathToFileURL(resolve(root,'packages/util/official-bundles/lib/index.js')).href)
mkdirSync(directory,{recursive:true});const result=[],anchor=join(directory,'install/package.json');mkdirSync(dirname(anchor));writeFileSync(anchor,'{"name":"install"}')
for(const [index,value] of JSON.parse(readFileSync(process.argv[3]!,'utf8')).entries()){
 const owner=join(directory,'legacy-'+index);initProfile(owner,[]);const manifest=join(owner,'package.json'),raw=JSON.parse(readFileSync(manifest,'utf8'))
 if(value!=='__absent__'){raw.dsh.profile.patchReload=value;writeFileSync(manifest,JSON.stringify(raw))}
 const before=readFileSync(manifest,'utf8'),loaded=loadProfileDirectory('test',owner,anchor)
 result.push({kind:'legacy',value,field:'patchReload'in loaded||'patch_reload'in loaded,unchanged:before===readFileSync(manifest,'utf8'),manifest:JSON.parse(readFileSync(manifest,'utf8')).dsh.profile})
}
const home=join(directory,'home'),retired=join(home,'profiles/headless');initProfile(retired,['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@deepseek-ai/dsh-headless'])
const manifest=join(retired,'package.json'),raw=JSON.parse(readFileSync(manifest,'utf8'));raw.dsh.profile.patchReload='retained-extension';writeFileSync(manifest,JSON.stringify(raw));loadProfile('test','headless',anchor,home)
result.push({kind:'retired',profile:JSON.parse(readFileSync(manifest,'utf8')).dsh.profile})
for(const mode of ['base','web-app','headless','sdk-app','acp-app','sdk-minimal']){
 const layers=['base','sdk-minimal'].includes(mode)?[]:[loadOverlayPatches('test',join(root,'packages/bundle/base/cordis.patch.yml'))]
 layers.push(loadOverlayPatches('test',join(root,'packages/bundle',mode,'cordis.patch.yml')))
 const row=composeEntries(layers).find(row=>row.id==='hmr')
 result.push({kind:'row',mode,row:row===undefined?null:Object.fromEntries(['name','disabled','config'].map(key=>[key,row[key]]))})
}
result.push({kind:'templates',values:Object.fromEntries(['acp','web','headless','sdk','sdk-minimal'].map(name=>[name,PROFILE_TEMPLATES[name]]))})
process.stdout.write(JSON.stringify(result))
