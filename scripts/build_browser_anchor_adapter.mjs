/** Reproduce the pinned CSS anchor adapter; all vendor edits are asserted. */
import assert from 'node:assert/strict';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {resolve, join} from 'node:path';
const options=Object.fromEntries(process.argv.slice(2).reduce((rows,value,index,args)=>{
  if(value.startsWith('--'))rows.push([value.slice(2),args[index+1]]);return rows;
},[]));
assert.ok(options.source&&options.esbuild,'Explicit extracted package and esbuild paths required');
const source=resolve(options.source),directory=resolve('dsh/host/browser_compat');
const require=createRequire(import.meta.url),builder=require(resolve(options.esbuild));
const manifest=JSON.parse(await readFile(join(source,'package.json'),'utf8'));
assert.equal(manifest.name,'@oddbird/css-anchor-positioning');assert.equal(manifest.version,'0.10.2');
assert.equal(builder.version,'0.25.12');
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const bytes=await readFile(join(source,'css-anchor-positioning-fn.js'));
assert.equal(hash(bytes),'3d81733ca68ad97aae0395ae4e3010dcf62d99ee828f0085f5cf6e2d70154ea0');
let code=bytes.toString('utf8');
function patch(before,after){assert.equal(code.split(before).length,2,`Vendor patch drift: ${before.slice(0,65)}`);code=code.replace(before,after);}
// Each refresh owns and releases Floating UI observers before discovering the
// new React portals. Never replace/remove React-owned style/link/inline nodes.
patch('function Ve(e, t, n, r) {',`var dshCleanups=[],dshTargets=new Set(),dshWrites=new Map();
function dshWrite(style,key,value){
  let prior=dshWrites.get(style);if(!prior){prior=new Map();dshWrites.set(style,prior);}
  if(!prior.has(key))prior.set(key,[style.getPropertyValue(key),style.getPropertyPriority(key)]);
  style.setProperty(key,value);
}
function dshRootSet(key,value){dshWrite(document.documentElement.style,key,value);}
function dshSetInline(node,key,value){dshWrite(node.style,key,'var('+value+')');}
function dshCreateStyle(){const node=document.createElement('style');node.setAttribute('data-generated-by-polyfill','true');return node;}
function dshAlign(target){
  if(!target.isConnected)return;
  const style=getComputedStyle(target);
  const x=style.justifySelf.replace('safe ','').replace('unsafe ',''),y=style.alignSelf.replace('safe ','').replace('unsafe ','');
  const value=x+'-x '+y+'-y';
  if(target.getAttribute('data-dsh-anchor-compat')!==value)target.setAttribute('data-dsh-anchor-compat',value);
}
function Ve(e,t,n,r){dshTargets.add(t);const release=dshAutoUpdate(e,t,()=>{dshAlign(t);return n();},r);dshCleanups.push(release);return release;}
function dshAutoUpdate(e, t, n, r) {`);
patch('function Su(e) {',`function dshInline(e){
  let css=(e.getAttribute("style")||"").replaceAll("--dsh-compat-anchor-name:","anchor-name:").replaceAll("--dsh-compat-position-anchor:","position-anchor:");
  const model=e.style.getPropertyValue("--dsh-model-anchor").trim();
  const menu=e.style.getPropertyValue("--dsh-menu-anchor").trim();
  const parent=e.style.getPropertyValue("--dsh-submenu-parent").trim();
  const name=model||menu||parent;
  if(/^--[A-Za-z0-9_-]+$/.test(name)){
    const target=parent||e.hasAttribute("data-menu-backing")||
      (model&&e.matches('[role="menu"],[role="group"]'));
    if(target)css+=";position-anchor:"+name;
    else if(model||e.hasAttribute("data-menu-material"))css+=";anchor-name:"+name;
  }
  return css;
}
function Su(e) {`);
patch('let t = e.getAttribute("style");\n\treturn t ? /(?:^|;)\\s*position-anchor\\s*:/i.test(t) : !1;','return /(?:^|;)\\s*position-anchor\\s*:/i.test(dshInline(e));');
patch('return xu.test((t = e.getAttribute("style")) == null ? "" : t);','return xu.test(dshInline(e));');
patch('${e.getAttribute("style")}','${dshInline(e)}');
patch('a.setAttribute("style", `${r.uuid}: var(${s}); \u0024{(g = a.getAttribute("style")) == null ? "" : g}`)',
  'dshSetInline(a,r.uuid,s)');
assert.equal(code.split('n.style.setProperty(').length-1,8);
code=code.replaceAll('n.style.setProperty(','dshRootSet(');
patch('.filter((e) => e !== null);','.filter((e) => e !== null && !e.el?.disabled && !e.el?.sheet?.disabled && /(?:anchor(?:-name|-size|-scope)?\\s*[(:]|position-(?:anchor|area|try)\\s*:)/.test(e.css));');
patch('let t = new URL(e.href, document.baseURI);\n\tif (_u(e) && t.origin === location.origin) return t;',
  'if (_u(e)) return window[Symbol.for("deepseek-win7.host.stylesheets")].url(e);');
const fetchStart=code.indexOf('\t\t\t\ttry {\n\t\t\t\t\tlet t = yield fetch(e.url.toString())');
const fetchEnd=code.indexOf('\n\t\t\t});',fetchStart);
assert.ok(fetchStart>0&&fetchEnd>fetchStart);
code=code.slice(0,fetchStart)+`                const row=window[Symbol.for("deepseek-win7.host.stylesheets")].read(e.el);
                const css=yield row?.ready;
                return css?{...e,css}:null;`+code.slice(fetchEnd);
patch('!e.hasAttribute(uu)','!e.hasAttribute(uu) && !e.hasAttribute("data-dsh-color-mix-fallback")');
const start=code.indexOf('function wf(e, t, n) {'),end=code.indexOf('\nfunction Tf(e)',start);
assert.ok(start>0&&end>start);
code=code.slice(0,start)+`var dshStyles=new WeakMap();
function wf(entries, inline, roots) {
  return entries.map(row=>{
    if (!row.changed) return {...row,changed:false};
    if(row.sheet) throw Error('Constructed anchor stylesheets require a separate qualified adapter');
    let node=dshStyles.get(row.el);
    if(!node?.isConnected){node=document.createElement('style');node.setAttribute('data-generated-by-polyfill','true');
      const previous=window[Symbol.for('deepseek-win7.host.color-mix')]?.current?.fallbackFor(row.el)||row.el;
      previous?.after(node);dshStyles.set(row.el,node);}
    let css=row.css;
    if(row.el?.hasAttribute('data-has-inline-styles')){
      const values=inline?.get(row.el);
      if(values){const at=css.indexOf('{')+1;css=css.slice(0,at)+Object.entries(values).map(([key,value])=>key+':var('+value+');').join('')+css.slice(at);}
    }
    for(const attribute of ['media','type','title']){
      const value=row.el?.getAttribute(attribute)??null;
      if(value===null)node.removeAttribute(attribute);else node.setAttribute(attribute,value);
    }
    if(row.el?.nonce)node.nonce=row.el.nonce;
    node.textContent=css;
    return {...row,changed:false};
  });
}`+code.slice(end);
// Vendor fallback rules are owned output too; omitting their marker creates an
// observer feedback loop and leaves obsolete UUID selectors in the document.
assert.ok(code.includes('document.createElement("style")'));
code=code.replaceAll('document.createElement("style")','dshCreateStyle()');
patch('export { rp as default, np as patchAndPolyfillConstructedStylesheets };',`function dshReset(){
  for(const release of dshCleanups.splice(0))release();
  for(const target of dshTargets){target.removeAttribute('data-dsh-anchor-compat');
    target.removeAttribute('data-anchor-polyfill');target.removeAttribute('data-anchor-polyfill-last-successful');}
  dshTargets.clear();
  document.querySelectorAll('[data-generated-by-polyfill]').forEach(node=>node.remove());
  for(const [style,properties] of dshWrites)for(const [key,[value,priority]] of properties){
    if(value)style.setProperty(key,value,priority);else style.removeProperty(key);
  }
  dshWrites.clear();
}
function dshObservers(){return dshCleanups.length;}
export {rp as apply,dshReset as reset,dshTargets as targets,dshAlign as align,dshObservers as observers};`);
const result=await builder.build({stdin:{contents:code,sourcefile:'css-anchor-positioning-fn.js'},write:false,
  bundle:true,platform:'browser',format:'iife',globalName:'dshAnchorVendor',target:'chrome108',minify:true,legalComments:'inline',
  banner:{js:'/* @oddbird/css-anchor-positioning 0.10.2 (BSD-3-Clause), bundled Floating UI (MIT), css-tree (MIT), nanoid (MIT). See anchor.LICENSE.txt and anchor-input.json. */'}});
const output=result.outputFiles[0].contents;
const record={schema:1,package:manifest.name,version:manifest.version,license:manifest.license,
  source:'https://github.com/oddbird/css-anchor-positioning',
  npm:JSON.parse(await readFile(join(source,'registry.json'),'utf8')).dist,
  input:{path:'dist/css-anchor-positioning-fn.js',bytes:bytes.length,sha256:hash(bytes)},
  build:{esbuild:builder.version,target:'chrome108',format:'iife',patches:['Collect/release autoUpdate observers','Preserve React stylesheet and inline ownership via generated adjacent rules','Read unsupported CSSOM anchor properties through custom-property bridge','Resolve pinned model and menu anchor variables','Read local stylesheets through the Host compatibility adapter','Expose reset for dynamic portal discovery']},
  output:{path:'anchor.js',bytes:output.length,sha256:hash(output)},
  licenseSha256:hash(await readFile(join(source,'LICENSE'))),
  thirdPartyLicenses:JSON.parse(await readFile(join(source,'third-party-inputs.json'),'utf8')),
  thirdPartyLicenseSha256:hash(await readFile(join(source,'third-party-LICENSE.txt')))};
if(options.check==='true'){
  assert.deepEqual(await readFile(join(directory,'anchor.js')),Buffer.from(output));
  assert.deepEqual(JSON.parse(await readFile(join(directory,'anchor-input.json'),'utf8')),record);
  assert.deepEqual(await readFile(join(directory,'anchor.third-party-LICENSE.txt')),await readFile(join(source,'third-party-LICENSE.txt')));
}else{
  await writeFile(join(directory,'anchor.js'),output);
  await writeFile(join(directory,'anchor.LICENSE.txt'),await readFile(join(source,'LICENSE')));
  await writeFile(join(directory,'anchor-input.json'),JSON.stringify(record,null,2)+'\n');
  await writeFile(join(directory,'anchor.third-party-LICENSE.txt'),await readFile(join(source,'third-party-LICENSE.txt')));
}
console.log(JSON.stringify(record.output));
