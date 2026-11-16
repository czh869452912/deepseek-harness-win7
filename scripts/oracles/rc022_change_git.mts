import fs from 'node:fs'
import fsp from 'node:fs/promises'
import path from 'node:path'
import crypto from 'node:crypto'
import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts')
const Runtime=(await load('packages/subprocess/subprocess-local/src/index.ts')).default
const {GitRunner,locateGitWorkspace,snapshotTree,diffTrees,treeBlob,blobText,ignoredPaths,gitlinkPaths}=await load('packages/deliverables/workspace-changes/src/git.ts')
const input=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8')),repo=path.join(input.files,'source'),ctx=new Context()
function repoState(){
 const result:any={},base=path.join(repo,'.git')
 function visit(file:string){if(!fs.existsSync(file))return;const st=fs.statSync(file);if(st.isDirectory()){for(const name of fs.readdirSync(file))visit(path.join(file,name))}else result[path.relative(base,file)]=crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')}
 for(const part of ['index','HEAD','refs','objects'])visit(path.join(base,part))
 return result
}
await ctx.plugin(Runtime)
const runner=new GitRunner(ctx.subprocess,'git',{timeoutMs:30000,outputMaxBytes:1048576}),signal=new AbortController().signal,state=repoState()
try{
 const workspace=await locateGitWorkspace(runner,repo,async()=>path.join(repo,'scratch'),signal)
 const before=await snapshotTree(runner,workspace,signal)
 await fsp.writeFile(path.join(repo,'tracked.txt'),'after turn\nsecond\n');await fsp.rename(path.join(repo,'rename.txt'),path.join(repo,'renamed.txt'))
 await fsp.unlink(path.join(repo,'untracked.txt'));await fsp.writeFile(path.join(repo,'added.txt'),'added\n');await fsp.writeFile(path.join(repo,'ignored.txt'),'ignored after turn\n')
 const after=await snapshotTree(runner,workspace,signal),listing=await diffTrees(runner,workspace,before,after,signal),contents=[]
 for(const name of ['tracked.txt','rename.txt','renamed.txt','added.txt','untracked.txt','ignored.txt','literal[1].txt','scratch']){
  const row:any={path:name}
  for(const [label,tree] of [['before',before],['after',after]]){const blob=await treeBlob(runner,workspace,tree,name,signal);row[label]=blob===null?null:{...blob,text:await blobText(runner,workspace,blob.oid,1048576,signal)}}
  contents.push(row)
 }
 const truncated=new GitRunner(ctx.subprocess,'git',{timeoutMs:30000,outputMaxBytes:10});let cap
 try{await diffTrees(truncated,workspace,before,after,signal);cap='unexpected'}catch(error:any){cap=error.message}
 const current=repoState(),untouched=Object.keys(state).length===Object.keys(current).length&&Object.entries(state).every(([key,value])=>current[key]===value)
 const result={before,after,listing,contents,same:await diffTrees(runner,workspace,before,before,signal),ignored:[...await ignoredPaths(runner,workspace,['ignored.txt','tracked.txt','added.txt'],signal)].sort(),links:[...await gitlinkPaths(runner,workspace,signal)].sort(),cap,untouched,indexScratch:(await fsp.readdir(workspace.scratch)).filter(name=>name.startsWith('index-'))}
 process.stdout.write(JSON.stringify([result]))
}finally{await ctx.fiber.dispose()}
