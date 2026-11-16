// Rebuild portable decoder vocabulary/data with the pinned Source Node runtime.
// No Node dependency is introduced into the product runtime.
import fs from 'node:fs'
if(process.version!=='v24.9.0')throw Error('requires the qualified Node v24.9.0 toolchain')
const target=process.argv[2]
if(!target||fs.existsSync(target))throw Error('provide a fresh owned output path')
const builtin=process.binding('natives')['internal/encoding']
const mapSource=builtin.slice(builtin.indexOf('const encodings = new SafeMap(['),builtin.indexOf('function getEncodingFromLabel'))
const aliases={},singleByte={},dbcs={}
const names=new Set(),multi=new Set(['utf-8','utf-16le','utf-16be','big5','euc-jp','iso-2022-jp','shift_jis','euc-kr','gbk','gb18030'])
for(const match of mapSource.matchAll(/\['([^']+)', '([^']+)'\]/g)){
 try{const d=new TextDecoder(match[1]);aliases[match[1]]=d.encoding;names.add(d.encoding)}catch{}
}
for(const name of names){
 if(multi.has(name))continue
 const table=new TextDecoder(name).decode(Uint8Array.from({length:256},(_,i)=>i))
 if([...table].length!==256)throw Error('unexpected non-single-byte encoding '+name)
 singleByte[name]=table
}
for(const name of ['big5','euc-jp','shift_jis','euc-kr','gbk','gb18030']){
 const decoder=new TextDecoder(name)
 function trace(bytes){const output=decoder.decode(Uint8Array.from(bytes),{stream:true}),tail=decoder.decode();return{output,tail}}
 function leaf(bytes){
  const {output,tail}=trace(bytes)
  if(!output)return null
  if(!tail)return[output,bytes.length]
  for(let count=bytes.length-1;count>0;count--){
   const suffix=trace(bytes.slice(-count))
   if(!suffix.output&&suffix.tail===tail)return[output,bytes.length-count]
  }
  throw Error('unidentified pending suffix '+name+' '+bytes)
 }
 const single=Array.from({length:256},(_,i)=>leaf([i])),pairs={},triples={}
 for(let first=0;first<256;first++){
  if(single[first]!==null)continue
  const row=Array.from({length:256},(_,second)=>leaf([first,second]));pairs[first]=row
  for(let second=0;second<256;second++){
   if(row[second]!==null||name==='gb18030')continue
   const third=Array.from({length:256},(_,byte)=>leaf([first,second,byte]))
   if(third.some(x=>x===null))throw Error('unexpected prefix longer than three bytes')
   triples[(first<<8)|second]=third
  }
 }
 dbcs[name]={single,pairs,triples}
 if(name==='gb18030'){
  const ranges=[],special={},bytes=new Uint8Array(4)
  let begin=0,previous=0,initial=0,step=null,active=false
  function flush(end){if(active)ranges.push([begin,end,initial,step??0]);active=false;step=null}
  for(let pointer=0;pointer<126*10*126*10;pointer++){
   let rest=pointer;bytes[3]=rest%10+0x30;rest=Math.floor(rest/10);bytes[2]=rest%126+0x81;rest=Math.floor(rest/126);bytes[1]=rest%10+0x30;bytes[0]=Math.floor(rest/10)+0x81
   const output=decoder.decode(bytes),points=[...output]
   if(points.length!==1){flush(pointer-1);special[pointer]=output;continue}
   const code=points[0].codePointAt(0),difference=code-previous
   if(active&&((step===null&&(difference===0||difference===1))||difference===step)){
    if(step===null)step=difference
   }else{flush(pointer-1);begin=pointer;initial=code;active=true}
   previous=code
  }
  flush(126*10*126*10-1);dbcs[name].ranges=ranges;dbcs[name].special=special
 }
}
const iso2022={single:[],pairs:{}}
const iso=new TextDecoder('iso-2022-jp')
function isoTrace(bytes){iso.decode(Uint8Array.of(27,36,66),{stream:true});const output=iso.decode(Uint8Array.from(bytes),{stream:true}),tail=iso.decode();return{output,tail}}
function isoLeaf(bytes){
 const {output,tail}=isoTrace(bytes)
 if(!output)return null
 if(!tail)return[output,bytes.length]
 if(bytes.length===2){const suffix=isoTrace(bytes.slice(1));if(!suffix.output&&suffix.tail===tail)return[output,1]}
 throw Error('unidentified ISO-2022-JP suffix '+bytes)
}
for(let first=0;first<256;first++){
 iso2022.single.push(first===27?null:isoLeaf([first]))
 if(first!==27&&iso2022.single[first]===null)iso2022.pairs[first]=Array.from({length:256},(_,second)=>isoLeaf([first,second]))
}
fs.writeFileSync(target,JSON.stringify({node:process.version,icu:process.versions.icu,aliases,singleByte,dbcs,iso2022})+'\n')
