/** Capture the original file-reference prompt callback without interpreting TS strings. */
import fs from 'node:fs'
import path from 'node:path'
import {pathToFileURL} from 'node:url'
const [source,output]=process.argv.slice(2)
const module=await import(pathToFileURL(path.resolve(source,'packages/deliverables/deliverable-file-references/lib/index.js')))
const sections=[]
module.apply({systemPrompt:{section(value){sections.push(value)},getSectionOrder(key){return key}}})
if(sections.length!==1)throw Error('unexpected file reference sections')
fs.writeFileSync(output,JSON.stringify(sections[0],null,2)+'\n','utf8')
