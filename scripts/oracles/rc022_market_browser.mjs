import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {deferCurrentProviderWithPlaywright} from '../current_browser_onboarding.mjs';
const [source,out]=process.argv.slice(2),root=process.cwd();
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const config=JSON.parse(await fs.readFile(path.join(out,'browser-config.json'),'utf8'));
const result={browserPlugin:'absent',fallback:'Browser plugin not available',steps:[],errors:[],responses:[],api:[],requests:[],passed:false};
let browser,page;const requestRefs=[],pending=new Map();
try {
 browser=await chromium.launch({executablePath:config.browser || path.join(root,'.goose/tools/chromium-1058931/chrome-win/chrome.exe'),headless:true});
 page=await browser.newPage({viewport:{width:1440,height:900}});page.setDefaultTimeout(10000);result.version=browser.version();
 page.on('request',request=>pending.set(request,{path:new URL(request.url()).pathname,started:Date.now()}));
 page.on('requestfinished',request=>pending.delete(request));page.on('requestfailed',request=>pending.delete(request));
 page.on('pageerror',error=>result.errors.push({message:error.message,stack:error.stack}));
 page.on('response',response=>{if(response.status()>=400)result.responses.push({url:response.url().replace(/token=[^&]+/g,'token=REDACTED'),status:response.status()})});
 page.on('response',async response=>{if(/\/api\/(pluginMarket|plugin-market|pluginRegistryProbe)\//.test(new URL(response.url()).pathname)){
  const body=await response.text().catch(()=>null);result.api.push({path:new URL(response.url()).pathname,status:response.status(),body:body?.slice(0,1400)});
 }});
 page.on('console',message=>{if(message.type()==='error')result.errors.push({message:message.text()})});
 page.on('request',request=>{if(new URL(request.url()).pathname.startsWith('/api/pluginMarket/')){result.requests.push({path:new URL(request.url()).pathname,body:request.postData()});requestRefs.push(request)}});
 page.on('requestfailed',request=>{const path=new URL(request.url()).pathname,failure=request.failure();
  if(path!=='/plugins/events'||failure?.errorText!=='net::ERR_ABORTED')result.errors.push({path,failure});
 });
 page.on('websocket',socket=>{if(socket.url().includes('/api/remote.mux'))result.remoteMux=true});
 await page.goto(config.url,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(插件|Plugins)$/}).waitFor({state:'visible',timeout:20000});
 const proceed=page.getByRole('button',{name:/^(继续|Continue)$/});
 if(config.cold){await proceed.waitFor({state:'hidden'});result.steps.push('welcome-acknowledgement-survived-process-restart')}
 else{await proceed.waitFor({state:'visible'});await proceed.click();await proceed.waitFor({state:'hidden'})}
 if(config.currentOnboarding) await deferCurrentProviderWithPlaywright(page);
 const dialog=page.getByRole('dialog');if(!config.currentOnboarding && await dialog.isVisible()){
  const close=dialog.getByRole('button').filter({hasText:/^$/});if(await close.count()===1)await close.click();
 }
 await page.getByRole('button',{name:/^(插件|Plugins)$/}).click();
 await page.getByText(/^(发现|Discover)$/,{exact:true}).click();result.steps.push('optional-original-discover-opened');
 if(!config.cold){
 // Discover waits for the installed host's settings, inventory and index list.
 await page.getByRole('button',{name:/^(添加索引源|Add index source)$/}).click({timeout:60000});
 await page.getByRole('textbox',{name:/^(索引 URL|Index URL)$/}).fill(config.index);
 await page.getByRole('button',{name:/^(添加|Add)$/}).click();
 await page.getByRole('dialog').getByRole('button',{name:/^(关闭|Close)$/}).click();
 }
 await page.getByRole('button',{name:/^(查看 Browser Market Fixture|View Browser Market Fixture)$/}).waitFor({state:'visible',timeout:60000});
 result.steps.push(config.cold?'saved-source-refetched-after-process-restart':'source-saved-and-listing-loaded');await page.screenshot({path:path.join(out,'browser-market-list.png')});
 await page.getByRole('searchbox',{name:/^(搜索插件|Search plugins)$/}).fill('searchable');
 await page.locator('[data-market-entry="browser-market-other"]').waitFor({state:'hidden'});
 result.steps.push('original-search-filtered');
 await page.getByRole('button',{name:/^(查看 Browser Market Fixture|View Browser Market Fixture)$/}).click();
 await page.getByRole('heading',{name:'Browser detail evidence',exact:true}).waitFor({state:'visible',timeout:20000});
 const image=page.getByRole('img',{name:'Market image'});await image.waitFor({state:'visible'});
 await image.evaluate(element=>{if(!element.complete||element.naturalWidth!==1)throw new Error('Adjacent image did not decode')});
 result.steps.push('original-detail-and-image-rendered');await page.screenshot({path:path.join(out,'browser-market-detail.png')});
 await page.reload({waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(插件|Plugins)$/}).click();
 await page.getByText(/^(发现|Discover)$/,{exact:true}).click();
 await page.getByRole('button',{name:/^(查看 Browser Market Fixture|View Browser Market Fixture)$/}).waitFor({state:'visible',timeout:60000});
 result.steps.push('saved-source-survived-reload');
 await page.setViewportSize({width:390,height:844});
 await page.getByRole('button',{name:/^(查看 Browser Market Fixture|View Browser Market Fixture)$/}).click();
 await page.getByRole('heading',{name:'Browser detail evidence',exact:true}).waitFor({state:'visible'});
 await page.screenshot({path:path.join(out,'browser-market-mobile.png')});result.steps.push('mobile-detail-rendered');
 result.passed=result.errors.length===0;
} catch(error){result.failure={message:error.message,stack:error.stack};result.pending=[...pending].map(([request,value])=>({...value,age:Date.now()-value.started,timing:request.timing()}));result.timings=requestRefs.map(request=>({path:new URL(request.url()).pathname,timing:request.timing()}));if(page){result.body=await page.locator('body').innerText().catch(()=>null);await page.screenshot({path:path.join(out,'browser-market-failure.png')}).catch(()=>{})}}
finally{if(browser)await browser.close();await fs.writeFile(path.join(out,'browser-observations.json'),JSON.stringify(result,null,2));}
console.log(JSON.stringify({passed:result.passed,steps:result.steps,failure:result.failure}));process.exitCode=result.passed?0:1;
