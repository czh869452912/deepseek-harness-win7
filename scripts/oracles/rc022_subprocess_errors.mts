import {load} from './rc022_subagent_fixture.mts'
const {HarnessError}=await load('packages/util/error/src/index.ts'),{SubprocessError,SubprocessExecutableNotFoundError,subprocessSpawnFailure,SUBPROCESS_ERROR_CODES}=await load('packages/subprocess/subprocess/src/error.ts'),rows:any[]=[]
for(const code of ['ENOENT','EACCES','EIO','',1,null]){
 const error=Object.assign(Error('platform failure'),{code}),value=subprocessSpawnFailure(error,'C:\\工具\\shell.exe') as any
 rows.push({name:'classify',input:code,same:value===error,harness:value instanceof HarnessError,code:value.code??null,message:value.message,cause:value.cause===error})
}
for(const value of ['raw',null,{code:'ENOENT'},new HarnessError('unavailable','SANDBOX_UNAVAILABLE'),new SubprocessError('owned','SUBPROCESS_RUNNER_FAILED')])rows.push({name:'preserve',same:subprocessSpawnFailure(value,'shell')===value})
const cause=Error('cause'),error=new SubprocessExecutableNotFoundError('missing',{cause})
rows.push({name:'lookup',harness:error instanceof HarnessError,subprocess:error instanceof SubprocessError,code:error.code,message:error.message,errorName:error.name,cause:error.cause===cause,codes:[...SUBPROCESS_ERROR_CODES]})
console.log(JSON.stringify(rows))
