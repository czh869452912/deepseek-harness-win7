/** Exercise the shipped guide's installed Python + plain-JS example. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir, mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {credentialFreeEnvironment, isolatedBrowserArguments, deferProviderOnboarding, navigateOriginalPage, closeOriginalBrowser} from './browser_onboarding.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => {
  if (value.startsWith('--')) rows.push([value.slice(2), all[index + 1]]); return rows;
}, []));
if (!args.browser || !args.output) throw new Error('Use --browser <Chromium> --output <report.json>');
const output = resolve(args.output);
await mkdir(dirname(output), {recursive: true});
const profile = await mkdtemp(join(tmpdir(), 'dsh-guide-cdp-'));
const report = {steps: [], errors: [], consoleErrors: [], passed: false};
const delay = ms => new Promise(done => setTimeout(done, ms));
async function until(read, label, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {const value = await read(); if (value) return value; await delay(100);}
  throw new Error('Timed out: ' + label);
}
let host, browser, cdp, hostErrors = '', nextCommand = 1;
const pending = new Map();
let bootValue, bootError;
class CDP {
  constructor(socket) {
    this.socket = socket; this.next = 1; this.pending = new Map();
    socket.addEventListener('message', event => {
      const item = JSON.parse(event.data);
      if (item.id) {
        const call = this.pending.get(item.id);
        if (call) {this.pending.delete(item.id); clearTimeout(call.timer); item.error ? call.no(new Error(JSON.stringify(item.error))) : call.yes(item.result);}
      } else if (item.method === 'Runtime.exceptionThrown') report.consoleErrors.push(item.params.exceptionDetails.text);
      else if (item.method === 'Runtime.consoleAPICalled' && item.params.type === 'error') report.consoleErrors.push(item.params.args.map(row => row.value ?? row.description).join(' '));
    });
  }
  call(method, params = {}) {
    const id = this.next++;
    return new Promise((yes, no) => {
      const timer = setTimeout(() => {this.pending.delete(id); no(new Error('CDP timeout: ' + method));}, 15000);
      this.pending.set(id, {yes, no, timer}); this.socket.send(JSON.stringify({id, method, params}));
    });
  }
  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}
function command(command) {
  const id = nextCommand++;
  return new Promise((yes, no) => {
    const timer = setTimeout(() => {pending.delete(id); no(new Error('Host timeout: ' + command));}, 60000);
    pending.set(id, {yes, no, timer}); host.stdin.write(JSON.stringify({id, command}) + '\n');
  });
}
async function click(selector) {
  const point = await until(() => cdp.evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); if(!e)return false; const b=e.getBoundingClientRect(); const x=b.x+b.width/2,y=b.y+b.height/2; return b.width && b.height && e.contains(document.elementFromPoint(x,y)) && {x,y};})()`), selector);
  for (const type of ['mousePressed', 'mouseReleased']) await cdp.call('Input.dispatchMouseEvent', {type, ...point, button: 'left', clickCount: 1});
}
async function open(url) {
  await navigateOriginalPage(cdp, until, url);
  await deferProviderOnboarding(cdp, until, false);
  await until(() => cdp.evaluate('document.querySelector("[data-win7-result]")?.textContent === "Ready"'), 'guide panel');
}
async function echo(expected, calls) {
  await click('[data-win7-call]');
  const value = await until(() => cdp.evaluate(`(() => {try {const v=JSON.parse(document.querySelector('[data-win7-result]')?.textContent); return v.calls === ${calls} && v;} catch {return false;}})()`), 'Python reply');
  assert.deepEqual(value, {text: expected, calls});
}
try {
  host = spawn(join(root, '.venv/Scripts/python.exe'), ['-u', join(root, 'scripts/win7_authoring_browser_host.py')], {cwd: root, windowsHide: true, env: credentialFreeEnvironment(process.env)});
  host.stderr.on('data', chunk => {hostErrors += chunk;});
  host.on('error', error => {bootError = error;});
  host.on('exit', code => {if (code) bootError = new Error('Host exited ' + code + ': ' + hostErrors);});
  createInterface({input: host.stdout}).on('line', line => {
    if (!line.startsWith('WIN7_GUIDE ')) return;
    const item = JSON.parse(line.slice('WIN7_GUIDE '.length));
    if (!item.id) {bootValue = item; return;}
    const call = pending.get(item.id);
    if (call) {pending.delete(item.id); clearTimeout(call.timer); item.error ? call.no(new Error(item.error)) : call.yes(item.value);}
  });
  const initial = await until(() => {if (bootError) throw bootError; return bootValue;}, 'Host startup', 60000);
  report.python = initial.python;
  let endpoint;
  browser = spawn(args.browser, isolatedBrowserArguments(profile), {windowsHide: true});
  browser.stderr.on('data', chunk => {const match = String(chunk).match(/DevTools listening on (ws:\/\/[^\s]+)/); if (match) endpoint = match[1];});
  await until(() => endpoint, 'browser endpoint');
  const port = new URL(endpoint).port;
  const pages = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  const socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((yes, no) => {socket.addEventListener('open', yes, {once: true}); socket.addEventListener('error', no, {once: true});});
  cdp = new CDP(socket);
  await cdp.call('Page.enable'); await cdp.call('Runtime.enable');
  await open(initial.url); await echo('中文 Win7', 1);
  const screenshot = await cdp.call('Page.captureScreenshot', {format: 'png'});
  await writeFile(output + '.png', Buffer.from(screenshot.data, 'base64'));
  report.steps.push('installed guide panel rendered and called Python');
  await open(initial.url); await echo('中文 Win7', 2);
  report.steps.push('page reload retained active Python state');
  await cdp.call('Page.navigate', {url: 'about:blank'});
  await until(() => cdp.evaluate('location.href === "about:blank"'), 'disconnect before restart');
  await open((await command('restart')).url); await echo('中文 Win7', 1);
  report.steps.push('cold restart loaded installed package');
  await cdp.call('Page.navigate', {url: 'about:blank'});
  await until(() => cdp.evaluate('location.href === "about:blank"'), 'disconnect before upgrade');
  await open((await command('upgrade')).url); await echo('中文 Win7 v2', 1);
  report.steps.push('upgrade selected new authored source');
  await cdp.call('Page.navigate', {url: 'about:blank'});
  await until(() => cdp.evaluate('location.href === "about:blank"'), 'disconnect before rollback');
  await open((await command('rollback')).url); await echo('中文 Win7', 1);
  report.steps.push('rollback restored retained source');
  assert.deepEqual(await command('unload'), {withdrawn: true, retainedRpcRevoked: true});
  await navigateOriginalPage(cdp, until, (await command('address')).url);
  await deferProviderOnboarding(cdp, until, false);
  await until(() => cdp.evaluate('!document.querySelector("[data-win7-authoring]")'), 'Client panel removed');
  report.steps.push('unload revoked retained Host RPC; page reload removed Client panel');
  assert.deepEqual(report.consoleErrors, []);
  report.passed = true;
} catch (error) {report.errors.push(error.stack || String(error));}
finally {
  try {if (cdp) await closeOriginalBrowser(cdp, browser, until); else if (browser) browser.kill();} catch (error) {report.errors.push(String(error));}
  try {if (host && host.exitCode === null) {await command('stop'); host.stdin.end(); await until(() => host.exitCode !== null, 'Host exit');}} catch (error) {report.errors.push(String(error)); if (host) host.kill();}
  for (const call of pending.values()) clearTimeout(call.timer);
  report.hostExitCode = host?.exitCode; report.hostErrors = hostErrors;
  report.passed = report.passed && report.errors.length === 0 && report.hostExitCode === 0 && !hostErrors;
  await writeFile(output, JSON.stringify(report, null, 2) + '\n');
  await rm(profile, {recursive: true, force: true, maxRetries: 10, retryDelay: 100});
}
console.log(JSON.stringify(report));
process.exitCode = report.passed ? 0 : 1;
