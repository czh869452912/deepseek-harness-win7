import {load} from './rc022_subagent_fixture.mts'
const {Context}=await load('vendor/cordis/src/index.ts'),{default:Controller}=await load('packages/api/settings-controller/src/index.ts')
const ctx=new Context(),rows:any[]=[],calls:any[]=[],opened:any[]=[]
let control=new AbortController(),mode='ok'
const descriptor={ns:'Mixed:entry',autoGenerate:false,schema:{type:'object'},value:{count:2},base:{count:1},user:{count:2},applies:'live',revision:3,secrets:[{path:['token'],set:true}],privateField:'discard'}
const provider={writable:true,describe:()=>[descriptor],prepareDocument:async()=>{if(mode==='cancel')control.abort();if(mode==='prepare-fail')throw Error('preparation failed');return 'owned.patch.yml'},
 update:async(ns:any,patch:any,expected:any)=>{calls.push([ns,patch,expected??null]);if(mode==='conflict')throw Object.assign(Error('stale'),{code:'SETTINGS_CONFLICT',expected:1,actual:3});if(mode==='reject')throw Error('refused')}}
async function observe(name:string,callback:()=>any){try{rows.push({name,value:await callback()})}catch(error:any){rows.push({name,error:{code:error.code,message:error.message,details:error.details}})}}
try{
 await ctx.plugin(Controller,{openTextFile:async(path:string)=>{if(mode==='open-fail')throw Error('open failed');opened.push(path)}})
 const api=ctx.settingsController
 await observe('missing',()=>api.describe());await observe('empty',()=>api.update('',{},undefined))
 ctx.provide('settings',provider)
 await observe('describe',()=>api.describe());await observe('update',()=>api.update('Mixed:entry',{count:4},undefined))
 mode='conflict';await observe('conflict',()=>api.update('Mixed:entry',{},1))
 mode='reject';await observe('rejected',()=>api.update('Mixed:entry',{},undefined))
 mode='ok';await observe('open',()=>api.openSettingsDocument(control.signal))
 mode='prepare-fail';await observe('prepare-fail',()=>api.openSettingsDocument(control.signal))
 mode='open-fail';await observe('open-fail',()=>api.openSettingsDocument(control.signal))
 mode='cancel';await observe('cancel-during-prepare',()=>api.openSettingsDocument(control.signal))
 await observe('already-cancelled',()=>api.openSettingsDocument(control.signal))
 rows.push({name:'calls',value:calls},{name:'opened',value:opened})
}finally{await ctx.fiber.dispose()}
process.stdout.write(JSON.stringify(rows))
