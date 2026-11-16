import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const {resolveAdapterOptions}=await load('packages/llm/llm-deepseek/src/config.ts')
fs.writeFileSync(process.argv[3]!,JSON.stringify(resolveAdapterOptions({}),null,2)+'\n')
