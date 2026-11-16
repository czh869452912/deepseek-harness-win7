// Derive default casing facts from the fixed Source toolchain's ICU Unicode 16.
import fs from 'node:fs';
if (process.versions.unicode !== '16.0') throw new Error('Unicode 16 toolchain required');
if (!process.argv[2]) throw new Error('Explicit output path required');
const lower=[],cased=[],ignorable=[];
const ranges=(target,code)=>{const last=target.at(-1);if(last&&last[1]===code-1)last[1]=code;else target.push([code,code])};
for(let code=0;code<=0x10ffff;code++){
 const value=String.fromCodePoint(code),result=value.toLowerCase();
 if(value!==result)lower.push([code,result]);
 if(/\p{Cased}/u.test(value))ranges(cased,code);
 if(/\p{Case_Ignorable}/u.test(value))ranges(ignorable,code);
}
fs.writeFileSync(process.argv[2],JSON.stringify({unicode:process.versions.unicode,lower,cased,ignorable})+'\n');
