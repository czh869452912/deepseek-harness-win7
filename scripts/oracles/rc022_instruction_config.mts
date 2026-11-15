import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const config=await load('packages/context/agent-instructions/src/config.ts'),scope=await load('packages/context/agent-instructions/src/render.ts'),homes=await load('packages/util/home-paths/src/index.ts'),cases=JSON.parse(readFileSync(new URL('./rc022_instruction_config_cases.json',import.meta.url),'utf8')),rows:any[]=[]
for(const entry of cases.configs){const value=config.resolveConfig(entry);rows.push({kind:'config',value,identity:config.workspaceBaselineIdentity(value,'C:/work/child','C:/work')})}
for(const entry of cases.roots){const home=homes.resolveDshHome(entry.configured,entry.env??{}),agents=homes.resolveAgentsHome(entry.configured,entry.env??{});rows.push({kind:'roots',home,agents,homeDisplay:homes.dshHomeDisplay(home),agentsDisplay:homes.agentsHomeDisplay(agents)})}
for(const path of cases.paths){const directory=scope.scopeForDisplayPath(path),key=scope.instructionScopeKey(path);rows.push({kind:'scope',path,directory,key,decoded:scope.decodeScopeKey(key),group:scope.instructionCandidateGroup(directory),globalDirectory:scope.isUserGlobalDirectory(directory),escaped:scope.escapeProjectDisplayPath(path)})}
rows.push({kind:'decode-old',value:scope.decodeScopeKey('old-scope')});process.stdout.write(JSON.stringify(rows))
