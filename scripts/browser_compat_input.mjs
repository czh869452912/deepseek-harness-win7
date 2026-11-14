/** Mirror the production Python host's ordered, UTF-8 index injection. */
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';

export async function browserCompatibilityInput(directory){
  const hash=value=>createHash('sha256').update(value).digest('hex');
  const files=[];let script='';
  for(const name of ['url.js','compat.js']){
    const path=join(directory,name),bytes=await readFile(path);
    files.push({path,sha256:hash(bytes)});
    script+=(script?'\n':'')+bytes.toString('utf8').replaceAll('\r\n','\n');
  }
  const workerPath=join(directory,'worker.js'),workerBytes=await readFile(workerPath);
  files.push({path:workerPath,sha256:hash(workerBytes)});
  const workers=workerBytes.toString('utf8').replaceAll('\r\n','\n').replace('__DSH_REALM_CODE__',JSON.stringify(script));
  script='(function(){\nconst legacy = typeof Iterator === "undefined" || '+
    'typeof Promise.withResolvers !== "function" || typeof AbortSignal.any !== "function" || '+
    'typeof Promise.try !== "function" || typeof Math.sumPrecise !== "function" || '+
    'typeof Uint8Array.fromBase64 !== "function" || typeof Uint8Array.prototype.toHex !== "function" || '+
    'typeof Uint8Array.prototype.toBase64 !== "function" || typeof Map.prototype.getOrInsertComputed !== "function" || '+
    'typeof Set.prototype.intersection !== "function" || '+
    'typeof Map.prototype.getOrInsert !== "function" || typeof ArrayBuffer.prototype.transferToFixedLength !== "function" || '+
    'typeof Array.prototype.toSorted !== "function" || '+
    '(typeof URL === "function" && new URL("dsh-resource://file/x").hostname !== "file");\n'+
    script+'\nif (legacy) {\n'+workers+'\n}\n})();';
  return {files,script,sha256:hash(script)};
}
