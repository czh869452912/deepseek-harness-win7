import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {compareText}=await load('packages/deliverables/workspace-changes/src/compare.ts')
const cases=JSON.parse(fs.readFileSync(process.argv[3]!,'utf8'))
process.stdout.write(JSON.stringify(cases.map((test:any)=>({case:test,result:compareText(test.before,test.after,test.timeoutMs)}))))
