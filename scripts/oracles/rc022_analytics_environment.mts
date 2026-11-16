import fs from 'node:fs/promises'
import os from 'node:os'
import childProcess from 'node:child_process'
import {EventEmitter} from 'node:events'
import {syncBuiltinESMExports} from 'node:module'
import {load} from './rc022_subagent_fixture.mts'
const {collectEnvironment}=await load('packages/client/product-analytics/src/environment.ts')
const inputs=JSON.parse(await fs.readFile(process.argv[3]!,'utf8')),rows:any[]=[]
const original={platform:os.platform,release:os.release,totalmem:os.totalmem,cpus:os.cpus,execFile:childProcess.execFile},arch=Object.getOwnPropertyDescriptor(process,'arch')!,root=process.env.SystemRoot
try{for(const entry of inputs){
 const selected={platform:'win32',app_arch:'x64',SystemRoot:'C:\\Windows',release:'10.0.26100',totalmem:17179869184,
  cpus:[{model:' Fixture CPU '},{model:'Fixture CPU'}],...entry.sources}
 const version=entry.version??{kind:'value',stdout:selected.platform==='darwin'?'ProductVersion: 14.1\nBuildVersion: 23A123':JSON.stringify({major:10,minor:0,build:'26100',revision:1})}
 const cpu=entry.cpu??{kind:'value',stdout:selected.platform==='darwin'?'hw.physicalcpu: 4\nhw.optional.arm64: 1':JSON.stringify([{cores:4,architecture:9}])}
 for(const field of ['platform','release','totalmem','cpus'])Object.assign(os,{[field]:()=>{if(selected[field]?.throw)throw Error('synthetic source failure');return structuredClone(selected[field])}})
 Object.defineProperty(process,'arch',{...arch,value:selected.app_arch})
 if(selected.SystemRoot===null)delete process.env.SystemRoot;else process.env.SystemRoot=selected.SystemRoot
 const calls:any[]=[]
 childProcess.execFile=((command:string,args:string[],options:any,callback:any)=>{
  calls.push({command,args,timeoutMillis:options.timeout,maxOutputBytes:options.maxBuffer})
  const result=command==='/usr/sbin/sysctl'||args.includes('-EncodedCommand')&&Buffer.from(args.at(-1)!,'base64').toString('utf16le').includes('Get-CimInstance')?cpu:version
  const child=new EventEmitter()
  queueMicrotask(()=>{
   const error=result.kind==='value'?null:Object.assign(Error('synthetic query failure'),{code:result.reason==='output-limit'?'ERR_CHILD_PROCESS_STDIO_MAXBUFFER':'FIXTURE',killed:result.reason==='timeout'})
   callback(error,result.stdout??'');child.emit('close',0)
  })
  return child
 }) as any
 syncBuiltinESMExports()
 const value=await collectEnvironment({timeoutMillis:123,maxOutputBytes:456,signal:new AbortController().signal})
 rows.push({value,calls})
}}finally{for(const field of ['platform','release','totalmem','cpus'])Object.assign(os,{[field]:original[field]});childProcess.execFile=original.execFile;Object.defineProperty(process,'arch',arch);if(root===undefined)delete process.env.SystemRoot;else process.env.SystemRoot=root;syncBuiltinESMExports()}
process.stdout.write(JSON.stringify(rows))
