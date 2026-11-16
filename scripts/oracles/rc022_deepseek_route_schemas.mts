import fs from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const api=await load('packages/llm/llm-deepseek-api-key/src/config.ts')
const account=await load('packages/llm/llm-deepseek-account/src/config.ts')
fs.writeFileSync(process.argv[3]!,JSON.stringify({apiKey:api.Config.toJSON(),account:account.Config.toJSON()},null,2)+'\n')
