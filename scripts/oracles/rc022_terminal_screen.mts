import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const inputs=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{pageLines,renderLines,lastContentRow,cursorLineStart}=await load('packages/api/terminal-controller/src/screen.ts'),segmenter=new Intl.Segmenter(undefined,{granularity:'grapheme'}),rows:any[]=[]
for(const [index,text] of inputs.strings.entries())rows.push({name:'grapheme',index,value:Array.from(segmenter.segment(text),(item:any)=>item.segment)})
for(const [index,test] of inputs.pages.entries())rows.push({name:'page',index,value:pageLines(test.lines,test.request)})
for(const [index,value] of inputs.buffers.entries()){
 const buffer={...value,length:value.lines.length,getLine:(row:number)=>value.lines[row]===undefined?undefined:{isWrapped:value.lines[row].isWrapped,translateToString:(trim:boolean)=>trim?value.lines[row].trimmed:value.lines[row].text}}
 rows.push({name:'buffer',index,last:lastContentRow(buffer),cursor:cursorLineStart(buffer),ranges:[[-1,100],[1,3],[2,2]].map(([from,to])=>renderLines(buffer,from,to))})
}
process.stdout.write(JSON.stringify(rows))
