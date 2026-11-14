import {mkdirSync,readFileSync,writeFileSync} from 'node:fs'
import {dirname,join,resolve} from 'node:path'
import {createRequire} from 'node:module'
import {pathToFileURL} from 'node:url'
const root=process.argv[2]!,input=process.argv[3]!,load=(p:string)=>import(pathToFileURL(resolve(root,p)).href)
const plugin=await load('packages/boot/app-boot/src/plugin-compatibility.ts'),profile=await load('packages/boot/app-boot/src/profile-compatibility.ts')
const semver=createRequire(resolve(root,'package.json'))('semver'),runtime=plugin.getDshRuntimeVersion(),result:any[]=[]
for(const [index,row] of JSON.parse(readFileSync(input,'utf8')).entries()) {
 if(row.kind==='range')result.push(row.requirement.trim()!==''&&semver.satisfies(row.version,row.requirement,{includePrerelease:true}))
 else if(row.kind==='exact')result.push(typeof row.value==='string'&&profile.isExactPluginVersion(row.value))
 else if(row.kind==='manifest') {
  try {
   const issue=plugin.evaluatePluginCompatibility(row.value,row.exempt?{'@example/plugin@2.0.0':[runtime]}:{},runtime)
   result.push({issue:issue??null,warning:issue?plugin.pluginCompatibilityWarning(issue):null})
  }catch(e){result.push({error:(e as Error).message})}
 } else {
  const directory=resolve(dirname(input),'files/source',String(index));mkdirSync(directory,{recursive:true})
  writeFileSync(join(directory,'compatibility.json'),JSON.stringify(row.value))
  const read=profile.readProfileCompatibility(directory);read.warnings=read.warnings.map((s:string)=>s.replaceAll(directory,'$PROFILE'));result.push(read)
 }
}
const directory=resolve(dirname(input),'files/source/writes');mkdirSync(directory,{recursive:true})
const observations:any[]=[]
for(const [name,version,enabled,accept] of [['plugin@1.0.0',runtime,true,false],['plugin@1.0.0','9.9.9',true,true],['plugin@1.0.0',runtime,true,true],['other@2.0.0',runtime,true,true],['plugin@1.0.0',runtime,true,true],['plugin@1.0.0','0.0.1',false,false],['plugin@1.0.0',runtime,false,false]] as const){
 let error=null
 try{await profile.setProfileVersionExemption(directory,name,version,enabled,accept)}catch(e){error=(e as Error).message}
 observations.push({error,read:profile.readProfileCompatibility(directory)})
}
result.push(observations)
process.stdout.write(JSON.stringify(result))
