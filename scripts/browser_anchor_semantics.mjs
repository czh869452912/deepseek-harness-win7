/** Real Chromium capability checks, independent of the application journey. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {browserCompatibilityInput} from './browser_compat_input.mjs';
const [source,out]=process.argv.slice(2),root=process.cwd();
assert.ok(source&&out,'Explicit Source and fresh output directory required');
await fs.mkdir(out,{recursive:false});
const {chromium}=await import(pathToFileURL(path.join(source,'node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs')));
const input=await browserCompatibilityInput(path.join(root,'dsh/host/browser_compat'));
const result={fallback:'Browser plugin not available',inputSha256:input.sha256,errors:[],rows:[],passed:false};
const browser=await chromium.launch({executablePath:path.join(root,'.goose/tools/chromium-1058931/chrome-win/chrome.exe'),headless:true});
try{
  const page=await browser.newPage({viewport:{width:900,height:600}});page.setDefaultTimeout(10000);
  page.on('pageerror',error=>result.errors.push(error.message));
  page.on('console',message=>{if(['error','warning'].includes(message.type()))result.errors.push(message.text())});
  const css=`#trigger{position:absolute;left:600px;top:80px;width:40px;height:30px}
    .target{position:fixed;top:max(12px,calc(anchor(bottom) + 4px));bottom:12px;
      left:12px;right:max(12px,anchor(right));width:144px;height:76px;
      margin:0;justify-self:end;align-self:start;
      --paint:color-mix(in srgb,#ff0000 50%,#0000ff);background:var(--paint)}`;
  await page.setContent(`<style id="original">${css}</style><button id="trigger">More</button>`);
  await page.addScriptTag({content:input.script});
  await page.evaluate(()=>document.documentElement.style.setProperty('--anchor-user','preserved','important'));
  result.version=browser.version();
  await page.evaluate(()=>{
    const style=document.querySelector('button').style;
    style.setProperty('anchor-name','--first','important');
    if(style.anchorName!=='--first'||style.getPropertyPriority('anchor-name')!=='important')throw Error('CSSOM bridge');
    style.anchorName='--trigger';
  });
  async function open(){await page.evaluate(()=>{
    const node=document.createElement('div');node.id='target';node.className='target';node.textContent='Run now';
    node.style.positionAnchor='--trigger';document.body.append(node);
  });}
  async function positioned(){await page.waitForFunction(()=>{
    const a=document.querySelector('button').getBoundingClientRect(),node=document.querySelector('.target');
    if(!node)return false;const m=node.getBoundingClientRect();
    return Math.abs(m.right-a.right)<1&&Math.abs(m.top-a.bottom-4)<1&&window.__dshAnchorCompatibility.error===null;
  });}
  async function capture(name){const row=await page.evaluate(()=>({state:{...window.__dshAnchorCompatibility},
    menu:document.querySelector('.target')?.getBoundingClientRect().toJSON(),
    generated:document.querySelectorAll('[data-generated-by-polyfill]').length,
    rootVariables:Array.from(document.documentElement.style).filter(key=>key.startsWith('--anchor-')).length}));
    result.rows.push({name,...row});return row;}
  await open();await positioned();const initial=await capture('first-open');
  assert.ok(initial.state.observers>0&&initial.state.targets===1);
  await page.waitForTimeout(500);await positioned();
  assert.equal((await capture('stable')).state.refreshes,initial.state.refreshes,'No feedback refresh loop');
  assert.equal(await page.locator('#original').textContent(),css,'Original stylesheet retained byte-for-byte');
  assert.equal(await page.locator('.target').evaluate(node=>getComputedStyle(node).backgroundColor),'rgb(128, 0, 128)');
  await page.evaluate(()=>document.querySelector('button').style.left='400px');await positioned();await capture('anchor-moved');
  await page.evaluate(()=>document.querySelector('#original').textContent=document.querySelector('#original').textContent.replace('width:144px','width:180px'));
  await page.waitForFunction(()=>document.querySelector('.target').getBoundingClientRect().width===180);await positioned();await capture('stylesheet-replaced');
  for(let index=0;index<12;index++){
    await page.locator('.target').evaluate(node=>node.remove());
    await page.waitForFunction(()=>window.__dshAnchorCompatibility.observers===0&&!window.__dshAnchorCompatibility.active);
    await open();await positioned();
    const row=await capture('reopen-'+index);assert.equal(row.state.observers,initial.state.observers);
    assert.equal(row.generated,initial.generated);assert.equal(row.rootVariables,initial.rootVariables);
  }
  await page.screenshot({path:path.join(out,'anchor-and-color-mix.png')});
  await page.locator('.target').evaluate(node=>node.remove());
  await page.waitForFunction(()=>window.__dshAnchorCompatibility.observers===0&&!window.__dshAnchorCompatibility.active);
  const removed=await capture('removed');assert.equal(removed.generated,0);assert.equal(removed.rootVariables,1);
  assert.equal(await page.evaluate(()=>document.documentElement.style.getPropertyValue('--anchor-user')),'preserved');
  assert.equal(await page.evaluate(()=>document.documentElement.style.getPropertyPriority('--anchor-user')),'important');
  await page.evaluate(()=>document.querySelector('button').style.removeProperty('anchor-name'));
  assert.equal(await page.locator('button').evaluate(node=>node.style.anchorName),'');
  assert.deepEqual(result.errors,[]);
  const external=await browser.newPage({viewport:{width:900,height:600}});
  await external.route('http://fixture.test/**',route=>{
    if (route.request().url().endsWith('/menu.css')) {
      return route.fulfill({contentType:'text/css',body:css+
        '#trigger{anchor-name:var(--dsh-model-anchor)}.target{position-anchor:var(--dsh-model-anchor)}'});
    }
    return route.fulfill({contentType:'text/html',body:
      '<link rel="stylesheet" href="/menu.css"><button id="trigger" style="--dsh-model-anchor:--picker">Model</button>'});
  });
  await external.goto('http://fixture.test/');
  await external.addScriptTag({content:input.script});
  await external.evaluate(()=>{
    const menu=document.createElement('div');
    menu.className='target';
    menu.role='menu';
    menu.style.setProperty('--dsh-model-anchor','--picker');
    document.body.append(menu);
  });
  await external.waitForFunction(()=>{
    const button=document.querySelector('#trigger'),menu=document.querySelector('.target');
    return Math.abs(menu.getBoundingClientRect().top-button.getBoundingClientRect().bottom-4)<1 &&
      getComputedStyle(menu).backgroundColor==='rgb(128, 0, 128)' && window.__dshAnchorCompatibility.targets===1;
  });
  result.rows.push({name:'external-model-stylesheet',state:await external.evaluate(()=>({...window.__dshAnchorCompatibility}))});
  const linkOverride=css.replace(' + 4px',' + 10px').replace('#ff0000','#00ff00')+
    '#trigger{anchor-name:var(--dsh-model-anchor)}.target{position-anchor:var(--dsh-model-anchor)}';
  await external.evaluate(text=>{
    document.querySelector('link').disabled=true;
    const replacement=document.createElement('style');
    replacement.id='replacement';
    replacement.textContent=text;
    document.head.append(replacement);
  },linkOverride);
  async function checkSheet(gap,backgroundColor) {
    await external.waitForFunction(({gap,backgroundColor})=>{
      const button=document.querySelector('#trigger'),menu=document.querySelector('.target');
      return Math.abs(menu.getBoundingClientRect().top-button.getBoundingClientRect().bottom-gap)<1 &&
        getComputedStyle(menu).backgroundColor===backgroundColor;
    },{gap,backgroundColor});
  }
  await checkSheet(10,'rgb(0, 128, 128)');
  result.rows.push({name:'inline-replacement',state:await external.evaluate(()=>({...window.__dshAnchorCompatibility}))});
  await external.evaluate(()=>{
    document.querySelector('#replacement').remove();
    document.querySelector('link').disabled=false;
  });
  await checkSheet(4,'rgb(128, 0, 128)');
  result.rows.push({name:'external-restored',state:await external.evaluate(()=>({...window.__dshAnchorCompatibility}))});
  await external.close();
  // Native capability detection leaves the CSSOM methods and state untouched.
  const native=await browser.newPage();await native.setContent('<div></div>');
  await native.evaluate(()=>{window.previousAnchorSetter=CSSStyleDeclaration.prototype.setProperty;
    const supports=CSS.supports.bind(CSS);CSS.supports=(...args)=>args[0]==='anchor-name: --dsh-native'||supports(...args);});
  await native.addScriptTag({content:input.script});
  assert.equal(await native.evaluate(()=>!window.__dshAnchorCompatibility&&window.previousAnchorSetter===CSSStyleDeclaration.prototype.setProperty),true);
  result.passed=true;
}catch(error){result.failure=error.stack;}
finally{await browser.close();await fs.writeFile(path.join(out,'observations.json'),JSON.stringify(result,null,2));}
console.log(JSON.stringify({passed:result.passed,rows:result.rows.length,errors:result.errors,failure:result.failure}));
if(!result.passed)process.exitCode=1;
