import {readFileSync} from 'node:fs'
import {load} from './rc022_subagent_fixture.mts'
const families=JSON.parse(readFileSync(process.argv[3]!,'utf8')),{Context}=await load('vendor/cordis/src/index.ts'),{default:Loader}=await load('vendor/loader/src/index.ts'),Theme=await load('packages/client/ui-theme/src/index.ts'),Locale=await load('packages/client/locale/src/index.ts'),{normalizeFontFamily}=await load('packages/client/ui-theme/src/theme-settings.ts')
const rows:any[]=families.map((value:string)=>({step:'family',input:value,output:normalizeFontFamily(value),idempotent:normalizeFontFamily(normalizeFontFamily(value))===normalizeFontFamily(value)})),ctx=new Context()
ctx.on('webserver/index-inject',(table:any[])=>table.push({kind:'script',placement:'head',text:'after'}))
try{
 await ctx.plugin(Loader);ctx.loader.builtins.theme=Theme;ctx.loader.builtins.locale=Locale
 const key=await ctx.loader.create({name:'cordis:theme',config:{}}),entry=ctx.loader.resolve(key),fiber=entry.fiber!
 await fiber.await();const collect=()=>{const table:any[]=[];ctx.emit('webserver/index-inject',table,{principal:{kind:'owner'}});return table}
 rows.push({step:'default',rows:collect()})
 for(const value of [{preference:'dark',fontSize:22,codeFontSize:16,terminalFontSize:20,textFontFamily:families[4],codeFontFamily:'Iosevka',terminalFontFamily:'MesloLGS NF'},{preference:'light',fontSize:10}]){await entry.update({config:value});await entry.fiber!.await();rows.push({step:'updated',sameFiber:entry.fiber===fiber,rows:collect()})}
 for(const value of [{preference:'sepia'},{fontSize:9},{fontSize:23},{codeFontSize:17},{terminalFontSize:9},{fontSize:14.5}]){let accepted=true;try{fiber.resolveConfig(value)}catch{accepted=false}rows.push({step:'invalid',input:value,accepted})}
 await fiber.dispose();rows.push({step:'disposed',rows:collect()})
 const localeKey=await ctx.loader.create({name:'cordis:locale',config:{}}),localeEntry=ctx.loader.resolve(localeKey),localeFiber=localeEntry.fiber!;await localeFiber.await()
 for(const value of [{},{preference:'en'},{preference:'pt-BR'},{preference:'zh-Hant-TW'},{preference:'bad locale'},{preference:'123'}]){let answer:any;try{const config=localeFiber.resolveConfig(value),preference=config.preference.get();answer={accepted:true,value:preference===undefined?{}:{preference}}}catch{answer={accepted:false}}rows.push({step:'locale',input:value,...answer})}
}finally{await ctx.fiber.dispose()}
console.log(JSON.stringify(rows))
