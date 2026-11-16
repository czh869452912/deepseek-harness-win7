import fs from 'node:fs'
import zlib from 'node:zlib'
if(process.version!=='v24.9.0')throw Error('requires qualified Node v24.9.0')
const target=process.argv[2]
if(!target||fs.existsSync(target))throw Error('provide a fresh owned output path')
const encoders={gzip:zlib.gzipSync,'x-gzip':zlib.gzipSync,deflate:zlib.deflateSync,br:zlib.brotliCompressSync,zstd:zlib.zstdCompressSync}
const rows=[],payload=Buffer.from('prefix 中文🙂 '+('ABC'.repeat(100)))
function add(label,data,coding,extra={}){rows.push({label,mode:'body',data:[...data],wireEncoding:coding,contentType:'text/plain',...extra})}
for(const [coding,encode]of Object.entries(encoders)){
 const data=encode(payload)
 add(coding+':valid',data,coding)
 add(coding+':empty',Buffer.alloc(0),coding)
 for(const length of [1,2,3,4,5,6,Math.floor(data.length/2),data.length-4,data.length-2,data.length-1])add(coding+':prefix'+length,data.subarray(0,length),coding)
 for(const tail of [Buffer.from('junk'),Buffer.alloc(4),data])add(coding+':tail'+tail.toString('hex').slice(0,8),Buffer.concat([data,tail]),coding)
 add(coding+':expanded',encode(Buffer.alloc(2*1024*1024,65)),coding,{limits:{maxResponseBytes:257}})
 add(coding+':declared',data,coding,{declared:true,limits:{maxResponseBytes:2}})
 add(coding+':upper',data,coding.toUpperCase())
 add(coding+':padding',data,' '+coding+' ')
 for(const status of [204,205,304])add(coding+':null'+status,Buffer.from('invalid'),coding,{status})
}
for(const codings of [['gzip','br','zstd'],Array(5).fill('gzip'),Array(6).fill('gzip')]){
 let data=payload;for(const coding of codings)data=encoders[coding](data)
 add('chain:'+codings.join(','),data,codings.join(','))
}
for(const coding of ['unknown','identity','gzip,unknown','unknown,gzip','gzip,,deflate',',,,,',',,,,,'])add('unknown:'+coding,zlib.gzipSync(payload),coding)
add('raw-deflate',zlib.deflateRawSync(payload),'deflate')
for(const declared of [false,true])add('gzip-long-padding',zlib.gzipSync(payload),'gzip',{wireSuffixByte:0,wireSuffixCount:70000,declared})
for(const status of [204,205,304])add('null-with-six-codings',Buffer.from('invalid'),'gzip,gzip,gzip,gzip,gzip,gzip',{status})
fs.writeFileSync(target,JSON.stringify({node:process.version,zlib:process.versions.zlib,zstd:process.versions.zstd,rows})+'\n')
