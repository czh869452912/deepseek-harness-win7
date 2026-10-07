import {execFileSync} from 'node:child_process'
import {createHash} from 'node:crypto'
import {readFileSync,writeFileSync} from 'node:fs'
import {createRequire} from 'node:module'
import {dirname,resolve} from 'node:path'
import {fileURLToPath} from 'node:url'
import {computeHunkDiffs,diffsFromMeta} from '../../reference/packages/fs/tool-fs/src/diff.ts'

const root=fileURLToPath(new URL('../../',import.meta.url))
const fixturePath=fileURLToPath(new URL('./diff-fixtures-v1.json',import.meta.url))
const fixtures=JSON.parse(readFileSync(fixturePath,'utf8'))
const rows=fixtures.cases.map((fixture:any)=>({name:'diff/'+fixture.name,value:computeHunkDiffs(fixture.path,fixture.before,fixture.after)}))
for(const [index,meta] of fixtures.metadata.entries())rows.push({name:'metadata/'+index,value:diffsFromMeta(meta)??null})
const require=createRequire(resolve(root,'reference/packages/fs/tool-fs/package.json'))
const dependencyRoot=dirname(require.resolve('diff/package.json'))
const inputPaths=[fixturePath,resolve(root,'reference/packages/fs/tool-fs/src/diff.ts'),resolve(root,'reference/pnpm-lock.yaml'),...['package.json','libesm/diff/base.js','libesm/diff/line.js','libesm/patch/create.js'].map(path=>resolve(dependencyRoot,path))]
const inputs=Object.fromEntries(inputPaths.map(path=>[path,createHash('sha256').update(readFileSync(path)).digest('hex')]))
writeFileSync(process.env.DSH_FS_OUTPUT!,JSON.stringify({sourceCommit:execFileSync('git',['-C',root+'reference','rev-parse','HEAD'],{encoding:'utf8'}).trim(),node:process.version,dependencyVersion:JSON.parse(readFileSync(resolve(dependencyRoot,'package.json'),'utf8')).version,inputs,rows},null,2)+'\n',{encoding:'utf8',flag:'wx'})
