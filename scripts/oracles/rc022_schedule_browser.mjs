import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {deferCurrentProviderWithPlaywright} from '../current_browser_onboarding.mjs';
const [source,out]=process.argv.slice(2),root=process.cwd();
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const config=JSON.parse(await fs.readFile(path.join(out,'browser-config.json'),'utf8'));
const result={browserPlugin:'absent',fallback:'Browser plugin not available',viewport:{width:1440,height:900},errors:[],responses:[],steps:[],passed:false};
let browser,page,heartbeat;
let progress=Promise.resolve();
function event(value){progress=progress.then(()=>fs.appendFile(path.join(out,'browser-progress.jsonl'),JSON.stringify({at:Date.now(),...value})+'\n'));}
try{
 browser=await chromium.launch({executablePath:config.browser || path.join(root,'.goose/tools/chromium-1058931/chrome-win/chrome.exe'),headless:true});
 page=await browser.newPage({viewport:result.viewport});result.version=browser.version();
 page.setDefaultTimeout(10000);
 page.on('pageerror',error=>{const row={kind:'pageerror',message:error.message,stack:error.stack};result.errors.push(row);event(row)});
 page.on('console',message=>{if(['warning','error'].includes(message.type())){const row={kind:message.type(),message:message.text()};result.errors.push(row);event(row)}});
 page.on('websocket',socket=>{if(socket.url().includes('/api/remote.mux'))result.remoteMux=true});
 let requests=0,recent=[];
 page.on('request',request=>{requests++;recent.push(new URL(request.url()).pathname);recent=recent.slice(-4)});
 heartbeat=setInterval(()=>page.evaluate(()=>window.__dshAnchorCompatibility).then(anchor=>event({kind:'heartbeat',requests,recent,anchor})).catch(()=>{}),2000);heartbeat.unref();
 page.on('response',response=>{if(response.status()>=400)result.responses.push({url:response.url().replace(/token=[^&]+/g,'token=REDACTED'),status:response.status()})});
 await page.goto(config.url,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).waitFor({state:'visible',timeout:20000});
 const proceed=page.getByRole('button',{name:/^(继续|Continue)$/});
 if(config.cold){
  if(await proceed.isVisible())throw Error('Welcome confirmation was not restored');
  result.steps.push('cold-process-welcome-restored');
 }else{await proceed.waitFor({state:'visible',timeout:10000});await proceed.click();await proceed.waitFor({state:'hidden',timeout:10000});}
 if(config.currentOnboarding) await deferCurrentProviderWithPlaywright(page);
 const dialog=page.getByRole('dialog');if(!config.currentOnboarding && await dialog.isVisible()){
  const close=dialog.getByRole('button').filter({hasText:/^$/});if(await close.count()===1)await close.click();
 }
 result.home=await page.locator('body').innerText();await page.screenshot({path:path.join(out,'browser-home.png')});
 event({step:'home-rendered',anchor:await page.evaluate(()=>window.__dshAnchorCompatibility)});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).click();
 event({step:'catalog-trigger-clicked'});
 const originalTitle=config.cold?'Browser Schedule edited':'Browser Schedule contract';
 const editedTitle=config.cold?'Browser Schedule cold edited':'Browser Schedule edited';
 const editedPrompt=config.cold?'Edited after cold process restart':'Edited by original browser';
 await page.getByText(originalTitle,{exact:true}).waitFor({state:'visible',timeout:60000});
 result.steps.push('original-schedule-catalog-loaded');result.catalog=await page.locator('body').innerText();
 await page.getByText(originalTitle,{exact:true}).click();
 await page.getByRole('button',{name:/^(暂停任务|Pause)$/}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-task-details-opened');result.detail=await page.locator('body').innerText();
 if(config.cold){
  if(await page.getByRole('textbox',{name:/^(自动化任务名称|Automation task name)$/}).inputValue()!=='Browser Schedule edited'
   ||await page.getByRole('textbox',{name:/^(自动化任务内容|Automation task content)$/}).inputValue()!=='Edited by original browser')throw Error('Saved task edits were not restored');
  result.steps.push('cold-process-task-edits-restored');
 }
 event({step:'details-opened'});
 await page.screenshot({path:path.join(out,'browser-task.png')});
 await page.getByRole('button',{name:/^(暂停任务|Pause)$/}).click();
 await page.getByRole('button',{name:/^(恢复任务|Resume)$/}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-pause-acknowledged');
 event({step:'paused'});
 await page.getByRole('button',{name:/^(恢复任务|Resume)$/}).click();
 await page.getByRole('button',{name:/^(暂停任务|Pause)$/}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-resume-acknowledged');
 event({step:'resumed'});
 await page.getByRole('textbox',{name:/^(自动化任务名称|Automation task name)$/}).fill(editedTitle);
 await page.getByRole('textbox',{name:/^(自动化任务内容|Automation task content)$/}).fill(editedPrompt);
 await page.getByRole('button',{name:/^(保存修改|Save changes)$/}).click();
 await page.getByRole('heading',{name:editedTitle,exact:true}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-edit-acknowledged');
 await page.reload({waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).click();
 const edited=page.getByText(editedTitle,{exact:true});await edited.waitFor({state:'visible',timeout:10000});await edited.click();
 await page.getByRole('button',{name:/^(暂停任务|Pause)$/}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-edit-survived-reload');
 await page.getByRole('button',{name:/^(自动化任务操作|Automation task actions)$/}).click();
 const run=page.getByRole('menuitem',{name:/^(立即执行|Run now)$/});await run.waitFor({state:'visible',timeout:10000});
 async function positioned(){await page.waitForFunction(()=>{
   const anchor=document.querySelector('[aria-label="自动化任务操作"],[aria-label="Automation task actions"]');
   const menu=document.querySelector('[role="menu"]');if(!anchor||!menu)return false;
   const a=anchor.getBoundingClientRect(),m=menu.getBoundingClientRect();
   return Math.abs(m.right-a.right)<2&&Math.abs(m.top-a.bottom-4)<2;
 },null,{timeout:15000});}
 await positioned();
 // A late compatibility refresh must not move an already positioned menu.
 await page.waitForTimeout(500);await positioned();
 result.menuGeometry={anchor:await page.getByRole('button',{name:/^(自动化任务操作|Automation task actions)$/}).boundingBox(),menu:await page.getByRole('menu').boundingBox()};
 result.anchorCompatibility=await page.evaluate(()=>window.__dshAnchorCompatibility);
 await page.screenshot({path:path.join(out,'browser-run-menu.png')});
 await page.keyboard.press('Escape');await page.getByRole('menu').waitFor({state:'hidden'});
 await page.getByRole('button',{name:/^(自动化任务操作|Automation task actions)$/}).click();await positioned();
 result.steps.push('original-menu-reopened-at-anchor');
 await page.setViewportSize({width:390,height:844});await positioned();
 result.mobileMenuGeometry={viewport:{width:390,height:844},anchor:await page.getByRole('button',{name:/^(自动化任务操作|Automation task actions)$/}).boundingBox(),menu:await page.getByRole('menu').boundingBox()};
 await page.screenshot({path:path.join(out,'browser-mobile-menu.png')});
 result.steps.push('original-menu-follows-mobile-resize');
 // A cold process restores the real one-minute delivery floor. Wait for the
 // original menu to admit the next run; do not edit its clock or stored task.
 await run.click({timeout:75000});
 await page.getByRole('tab',{name:/^(任务运行记录|Records)$/}).click();
 const deliveries=page.getByRole('region',{name:/^(已保存的任务运行记录|Saved delivery record)$/});
 await deliveries.first().waitFor({state:'visible',timeout:15000});
 await page.waitForFunction(expected=>document.querySelectorAll('section[aria-label="已保存的任务运行记录"],section[aria-label="Saved delivery record"]').length===expected,config.cold?2:1,{timeout:15000});
 result.savedDeliveryRecords=await deliveries.count();
 result.steps.push('original-run-delivery-history-visible');result.history=await page.locator('body').innerText();
 await page.screenshot({path:path.join(out,'browser-delivery.png')});
 result.url=page.url().replace(/token=[^&]+/g,'token=REDACTED');result.title=await page.title();
 if(result.title!=='DeepSeek Harness'||!result.remoteMux||result.errors.length)throw Error('Identity, Remote or console check failed');
 result.passed=true;
}catch(error){
 result.failure=error.message.replace(/token=[^&\s]+/g,'token=REDACTED');
 if(page){result.body=await page.locator('body').innerText().catch(()=>null);await page.screenshot({path:path.join(out,'browser-failure.png')}).catch(()=>{});}
}finally{
 clearInterval(heartbeat);if(browser)await browser.close();await progress;await fs.writeFile(path.join(out,'browser-observations.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:result.passed,steps:result.steps,failure:result.failure,errors:result.errors}));
}
if(!result.passed)process.exitCode=1;
