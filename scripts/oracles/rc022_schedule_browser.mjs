import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [source,out]=process.argv.slice(2),root=process.cwd();
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const config=JSON.parse(await fs.readFile(path.join(out,'browser-config.json'),'utf8'));
const result={browserPlugin:'absent',fallback:'Browser plugin not available',viewport:{width:1440,height:900},errors:[],responses:[],steps:[],passed:false};
let browser,page;
try{
 browser=await chromium.launch({executablePath:path.join(root,'.goose/tools/chromium-1058931/chrome-win/chrome.exe'),headless:true});
 page=await browser.newPage({viewport:result.viewport});result.version=browser.version();
 page.on('pageerror',error=>result.errors.push({kind:'pageerror',message:error.message,stack:error.stack}));
 page.on('console',message=>{if(['warning','error'].includes(message.type()))result.errors.push({kind:message.type(),message:message.text()})});
 page.on('websocket',socket=>{if(socket.url().includes('/api/remote.mux'))result.remoteMux=true});
 page.on('response',response=>{if(response.status()>=400)result.responses.push({url:response.url().replace(/token=[^&]+/g,'token=REDACTED'),status:response.status()})});
 await page.goto(config.url,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).waitFor({state:'visible',timeout:20000});
 const proceed=page.getByRole('button',{name:/^(继续|Continue)$/});await proceed.waitFor({state:'visible',timeout:10000});await proceed.click();await proceed.waitFor({state:'hidden',timeout:10000});
 const dialog=page.getByRole('dialog');if(await dialog.isVisible()){
  const close=dialog.getByRole('button').filter({hasText:/^$/});if(await close.count()===1)await close.click();
 }
 result.home=await page.locator('body').innerText();await page.screenshot({path:path.join(out,'browser-home.png')});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).click();
 await page.getByText('Browser Schedule contract',{exact:true}).waitFor({state:'visible',timeout:20000});
 result.steps.push('original-schedule-catalog-loaded');result.catalog=await page.locator('body').innerText();
 await page.getByText('Browser Schedule contract',{exact:true}).click();
 await page.getByRole('button',{name:/^(暂停任务|Pause)$/}).waitFor({state:'visible',timeout:10000});
 result.steps.push('original-task-details-opened');result.detail=await page.locator('body').innerText();
 await page.screenshot({path:path.join(out,'browser-task.png')});
 result.url=page.url().replace(/token=[^&]+/g,'token=REDACTED');result.title=await page.title();
 if(result.title!=='DeepSeek Harness'||!result.remoteMux||result.errors.length)throw Error('Identity, Remote or console check failed');
 result.passed=true;
}catch(error){
 result.failure=error.message.replace(/token=[^&\s]+/g,'token=REDACTED');
 if(page){result.body=await page.locator('body').innerText().catch(()=>null);await page.screenshot({path:path.join(out,'browser-failure.png')}).catch(()=>{});}
}finally{
 if(browser)await browser.close();await fs.writeFile(path.join(out,'browser-observations.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:result.passed,steps:result.steps,failure:result.failure,errors:result.errors}));
}
if(!result.passed)process.exitCode=1;
