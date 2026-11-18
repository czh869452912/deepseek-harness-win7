/** Bind the current Host/frontend and the explicitly retained Win7 shell inputs. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {execFileSync} from 'node:child_process';
const options=Object.fromEntries(process.argv.slice(2).reduce((rows,value,index,args)=>{
  if(value.startsWith('--'))rows.push([value.slice(2),args[index+1]]);return rows;
},[]));
assert.ok(options.source,'Explicit clean current Source checkout required');
const root=resolve(import.meta.dirname,'..'),source=resolve(options.source);
const baseline=JSON.parse(await readFile(join(root,'migration/baseline.json'),'utf8'));
assert.equal(execFileSync('git',['-C',source,'rev-parse','HEAD'],{encoding:'utf8'}).trim(),baseline.target_upstream);
assert.equal(execFileSync('git',['-C',source,'status','--porcelain'],{encoding:'utf8'}).trim(),'');
const hash=value=>createHash('sha256').update(value).digest('hex');
const originPath='apps/desktop/compatibility-source-input.json',originBytes=await readFile(join(root,originPath));
const origin=JSON.parse(originBytes);
assert.equal(origin.sourceCommit,'a4c74a91e06b00fe0b0937bde982170c526cc842');
for(const row of origin.inputs)assert.equal(hash(await readFile(join(root,row.target))),row.sha256,'Retained Win7 input changed: '+row.target);
const protocolPath='apps/desktop/src/host-protocol.ts',protocolBytes=await readFile(join(source,protocolPath));
const generation=protocolBytes.toString('utf8').match(/DESKTOP_HOST_PROTOCOL_VERSION = (\d+) as const/u);
assert.ok(generation,'Current Desktop release protocol metadata missing');
const frontendPath='scripts/frontend-inputs.json',frontendBytes=await readFile(join(root,frontendPath));
const manifest={schema:2,targetUpstream:baseline.target_upstream,
  scope:'Current Native Host/profile and unchanged current Web frontend in the retained Win7 Electron22 shell. This is not the upstream Electron44 shell/UI or its protocol-v4 lifecycle implementation.',
  upstreamDesktopProtocol:{version:Number(generation[1]),source:protocolPath,sha256:hash(protocolBytes)},
  frontend:{manifest:frontendPath,sha256:hash(frontendBytes)},
  compatibility:{manifest:originPath,sha256:hash(originBytes),sourceCommit:origin.sourceCommit,
    carrierVersion:3,scope:'Retained socket-free Win7 pipe adapter, locale/plugin UI and injected full-installer coordinator; original provenance is preserved and is never relabelled as current upstream code.'}};
const data=JSON.stringify(manifest,null,2)+'\n';
if(options.check==='true')assert.equal(await readFile(join(root,'apps/desktop/source-input.json'),'utf8'),data);
else await writeFile(join(root,'apps/desktop/source-input.json'),data);
console.log(JSON.stringify({status:options.check==='true'?'verified':'built',target:manifest.targetUpstream,
  upstreamProtocol:manifest.upstreamDesktopProtocol.version,win7Carrier:3,compatibilityInputs:origin.inputs.length}));
