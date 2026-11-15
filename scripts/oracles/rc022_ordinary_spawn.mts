import {readFileSync} from 'node:fs'
import {join} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const workspace=readFileSync(process.argv[3]!,'utf8'),{Context}=await load('vendor/cordis/src/index.ts'),{default:Local}=await load('packages/subprocess/subprocess-local/src/index.ts'),{subprocessSpawnFailure}=await load('packages/subprocess/subprocess/src/error.ts'),ctx=new Context(),owner=await ctx.plugin(Local),runtime=ctx.subprocess,rows:any[]=[]
const cases:any[]=[['collect',"process.stdout.write('hello你好');process.stderr.write('warn');process.exitCode=5",'ignore',{maxBytes:100}],['tail',"process.stdout.write('x'.repeat(1000)+'END')",'ignore',{maxBytes:64}],['batch',"let n=0;process.stdin.on('data',b=>n+=b.length);process.stdin.on('end',()=>process.stdout.write(String(n)))",{data:'汉'.repeat(100000)},{maxBytes:100}],['pipe',"process.stdin.pipe(process.stdout)",'pipe','pipe'],['missing','', 'ignore',{maxBytes:100}]]
try{
 console.error(JSON.stringify({ordinaryContainment:(runtime as any).selectContainmentMode('ordinary')}))
 for(const [name,code,stdin,stdout] of cases){
  const program=name==='missing'?join(workspace,'missing-program.exe'):process.execPath,handle=runtime.spawn({argv:[program,'-e',code],cwd:workspace,stdio:{stdin,stdout,stderr:{maxBytes:100}},graceMs:100})
  let piped:any=null
  if(name==='pipe'){handle.stdin.end('raw input');const chunks=[];for await(const chunk of handle.stdout)chunks.push(chunk);piped=Buffer.concat(chunks).toString('utf8')}
  let result:any;try{result={value:await handle.done}}catch(error){result={errorCode:(subprocessSpawnFailure(error,program) as any).code}}
  await handle.waitForExit()
  rows.push({name,result,stdout:handle.collected.stdout?.readFrom(0)??null,stderr:handle.collected.stderr.readFrom(0),piped,stdin:handle.stdin!==undefined,stdoutPipe:handle.stdout!==undefined})
 }
 console.log(JSON.stringify(rows))
}finally{await owner.dispose();await ctx.fiber.dispose()}
