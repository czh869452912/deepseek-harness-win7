import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {deferCurrentProviderWithPlaywright} from '../current_browser_onboarding.mjs';
const [source,out]=process.argv.slice(2);
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const config=JSON.parse(await fs.readFile(path.join(out,'browser-config.json'),'utf8'));
const result={browserPlugin:'absent',fallback:'Browser plugin not available',errors:[],responses:[],steps:[],passed:false};
let browser,page;
try{
 browser=await chromium.launch({executablePath:config.browser,headless:true});
 page=await browser.newPage({viewport:{width:1440,height:900}});result.version=browser.version();page.setDefaultTimeout(15000);
 page.on('pageerror',error=>result.errors.push({kind:'pageerror',message:error.message}));
 page.on('console',message=>{if(['warning','error'].includes(message.type()))result.errors.push({kind:message.type(),message:message.text()})});
 page.on('websocket',socket=>{if(socket.url().includes('/api/remote.mux'))result.remoteMux=true});
 page.on('response',async response=>{if(response.status()>=400)result.responses.push({url:response.url().replace(/token=[^&]+/g,'token=REDACTED'),status:response.status(),body:await response.text().catch(()=>null)})});
 await page.goto(config.url,{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:/^(自动化任务|Automation tasks)$/}).waitFor({state:'visible',timeout:30000});
 const proceed=page.getByRole('button',{name:/^(继续|Continue)$/});
 if(config.cold){if(await proceed.isVisible())throw Error('Welcome confirmation was not restored')}
 else{await proceed.waitFor({state:'visible'});await proceed.click();await proceed.waitFor({state:'hidden'})}
 if(config.currentOnboarding)await deferCurrentProviderWithPlaywright(page);
 const dialog=page.getByRole('dialog');if(!config.currentOnboarding&&await dialog.isVisible()){
  const close=dialog.getByRole('button').filter({hasText:/^$/});if(await close.count()===1)await close.click();
 }
 const bucket=page.getByRole('treeitem').filter({has:page.getByText(/^(未分组|Ungrouped)$/)});
 if(await bucket.getAttribute('aria-expanded')==='false')await bucket.click();
 await page.getByText('Browser Timed Question',{exact:true}).first().click();
 await page.getByText(/^(已继续工作，仍可回答|Work continued — you can still answer)$/).last().waitFor({state:'visible'});
 await page.getByRole('heading',{name:'Choose the retained question result.',exact:true}).waitFor({state:'visible'});
 result.steps.push(config.cold?'cold-process-pending-question-restored':'timed-out-question-remained-answerable');
 await page.screenshot({path:path.join(out,'browser-question-pending.png')});
 const answer=page.getByRole('radio',{name:'Late answer',exact:true});await answer.click();await answer.press('Enter');
 const reply=page.getByRole('group',{name:/^(问题与回答|Questions and answers)$/}).last();await reply.waitFor({state:'visible'});
 if(!(await reply.innerText()).includes('Late answer'))throw Error('Admitted late answer is missing');
 result.steps.push('original-late-answer-remote-admitted');result.reply=await reply.innerText();
 await page.reload({waitUntil:'domcontentloaded'});
 await page.getByRole('group',{name:/^(问题与回答|Questions and answers)$/}).last().waitFor({state:'visible'});
 result.steps.push('admitted-answer-survived-browser-reload');
 await page.screenshot({path:path.join(out,'browser-question-answered.png')});
 if(!result.remoteMux||result.errors.length||result.responses.length)throw Error('Remote or browser errors');
 result.passed=true;
}catch(error){
 result.failure=error.message.replace(/token=[^&\s]+/g,'token=REDACTED');
 if(page){result.body=await page.locator('body').innerText().catch(()=>null);await page.screenshot({path:path.join(out,'browser-failure.png')}).catch(()=>{})}
}finally{
 if(browser)await browser.close();await fs.writeFile(path.join(out,'browser-observations.json'),JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:result.passed,steps:result.steps,failure:result.failure,errors:result.errors}));
}
if(!result.passed)process.exitCode=1;
