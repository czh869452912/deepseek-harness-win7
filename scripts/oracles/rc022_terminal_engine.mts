import {readFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {resolve} from 'node:path'
import {load} from './rc022_subagent_fixture.mts'
const require=createRequire(resolve(process.argv[2]!,'packages/api/terminal-controller/package.json')),{Terminal}=require('@xterm/headless'),{SerializeAddon}=require('@xterm/addon-serialize'),{pageLines,renderLines,lastContentRow,cursorLineStart}=await load('packages/api/terminal-controller/src/screen.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8')),rows:any[]=[]
for(const [index,actions] of cases.entries()){
 const terminal=new Terminal({cols:10,rows:4,scrollback:6,allowProposedApi:true}),serializer=new SerializeAddon(),marks=new Map<string,any>();terminal.loadAddon(serializer)
 function mark(){const buffer=terminal.buffer.active,marked=buffer.type,marker=terminal.registerMarker(cursorLineStart(buffer)-buffer.baseY-buffer.cursorY);return()=>{const active=terminal.buffer.active,end=lastContentRow(active)+1;if(active.type!==marked||marker===undefined)return {lines:renderLines(active,0,end),truncated:false};if(marker.isDisposed)return {lines:renderLines(active,0,end),truncated:true};return {lines:renderLines(active,marker.line,end),truncated:false}}}
 try{
  for(const [step,action] of actions.entries()){
   if(action[0]==='write')await new Promise<void>(done=>terminal.write(action[1],done))
   else if(action[0]==='resize')terminal.resize(action[1],action[2])
   else if(action[0]==='mark')marks.set(action[1],mark())
   const buffer=terminal.buffer.active,lines=renderLines(buffer,0,lastContentRow(buffer)+1)
   rows.push({case:index,step,snapshot:serializer.serialize(),page:pageLines(lines,{offset:0,count:100,maxBytes:10000}),small:pageLines(lines,{offset:1,count:2,maxBytes:7}),marks:Object.fromEntries([...marks].map(([name,read])=>[name,read()]))})
  }
 }finally{terminal.dispose()}
}
rows.push({name:'disposed',engines:0,workers:0});process.stdout.write(JSON.stringify(rows))
