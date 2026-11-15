import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const renderer=await load('packages/context/agent-instructions/src/render.ts'),cases=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
process.stdout.write(JSON.stringify(cases.map((entry:any)=>({name:entry.name,kind:entry.kind,value:entry.kind==='baseline'?renderer.renderAgentInstructionSet(entry.files,entry.options):renderer.renderInstructionChanges(entry.items,entry.budget)}))))
