import {createRequire} from 'node:module'
import {resolve} from 'node:path'
import {readFileSync} from 'node:fs'
const root=process.argv[2]!,input=JSON.parse(readFileSync(process.argv[3]!,'utf8'))
const match=createRequire(resolve(root,'packages/boot/hmr/package.json'))('picomatch')
process.stdout.write(JSON.stringify(input.patterns.map((pattern:string)=>({pattern,values:input.paths.map((path:string)=>match(pattern)(path))}))))
