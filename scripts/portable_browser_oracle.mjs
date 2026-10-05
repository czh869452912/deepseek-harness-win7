/** Development observer of an extracted Portable Host and unchanged browser UI. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline';
import {closeOriginalBrowser, deferProviderOnboarding, isolatedBrowserArguments, navigateOriginalPage} from './browser_onboarding.mjs';

const options = Object.fromEntries(process.argv.slice(2).reduce((rows, value, i, args) => {
  if (value.startsWith('--')) rows.push([value.slice(2), args[i + 1]]); return rows;
}, []));
for (const key of ['python', 'workspace', 'environment', 'browser', 'output']) {
  if (!options[key]) throw new Error('Missing --' + key);
}
const report = {passed: false, steps: [], exceptions: [], consoleErrors: [], sockets: [], replies: [], sessionRequests: []};
report.observedSessionWire = [];
const privateBrowser = await mkdtemp(join(tmpdir(), 'dsh-portable-cdp-'));
let host, browser, cdp, hostErrors = '';
const delay = ms => new Promise(done => setTimeout(done, ms));
const exited = child => child.exitCode !== null || child.signalCode !== null;
async function until(read, label, timeout = 25000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {const value = await read(); if (value) return value; await delay(100);}
  throw new Error('Timed out: ' + label);
}
class CDP {
  constructor(socket) {
    this.socket = socket; this.next = 1; this.pending = new Map(); this.listeners = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (!message.id) {for (const listener of this.listeners) listener(message); return;}
      const job = this.pending.get(message.id);
      if (!job) return;
      this.pending.delete(message.id); clearTimeout(job.timer);
      message.error ? job.no(new Error(JSON.stringify(message.error))) : job.yes(message.result);
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
    const result = await this.call('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}
const count = selector => cdp.evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
async function press(point) {
  await cdp.call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
  await cdp.call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
}
async function click(selector) {
  const point = await until(() => cdp.evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});
    if(!e) return false; const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2;
    return r.width && e.contains(document.elementFromPoint(x,y)) && {x,y};})()`), selector);
  await press(point);
}
try {
  const env = JSON.parse(await readFile(options.environment, 'utf8'));
  let readyYes, readyNo;
  const ready = new Promise((yes, no) => {readyYes = yes; readyNo = no;});
  const timer = setTimeout(() => readyNo(new Error('Extracted Host startup timeout')), 30000);
  host = spawn(resolve(options.python), ['-I', '-u', join(dirname(fileURLToPath(import.meta.url)), 'portable_runtime_probe.py'),
    '--workspace', resolve(options.workspace), '--serve'], {cwd: options.workspace, env, windowsHide: true});
  host.stderr.on('data', data => {hostErrors += data;});
  host.on('error', readyNo); host.on('exit', code => readyNo(new Error('Host exited: ' + code)));
  createInterface({input: host.stdout}).on('line', line => {
    if (!line.startsWith('PORTABLE_PROBE ')) return;
    const message = JSON.parse(line.slice('PORTABLE_PROBE '.length));
    if (message.ready) readyYes(message.value);
  });
  const boot = await ready.finally(() => clearTimeout(timer));
  report.identity = boot.identity;
  report.installedClientEntry = boot.graph.entries.find(row => row.id === '@verification/portable-web');
  assert.ok(report.installedClientEntry, 'installed package is declared in the active original module graph');
  report.moduleResponses = [];
  browser = spawn(resolve(options.browser), isolatedBrowserArguments(privateBrowser), {windowsHide: true});
  const port = await until(async () => {try {return (await readFile(join(privateBrowser, 'DevToolsActivePort'), 'utf8')).split('\n')[0];} catch {return false;}}, 'browser port');
  const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(row => row.type === 'page');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((yes, no) => {socket.addEventListener('open', yes, {once: true}); socket.addEventListener('error', no, {once: true});});
  cdp = new CDP(socket);
  const requests = new Map();
  const replyJobs = new Set();
  cdp.listeners.push(message => {
    if (message.method === 'Runtime.exceptionThrown') report.exceptions.push(message.params.exceptionDetails);
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') report.consoleErrors.push(message.params.args.map(row => row.value ?? row.description));
    if (message.method === 'Network.responseReceived' && new URL(message.params.response.url).pathname.startsWith('/plugins/')) {
      const url = new URL(message.params.response.url); report.moduleResponses.push({path: url.pathname + url.search, status: message.params.response.status});
    }
    if (message.method === 'Network.webSocketCreated') report.sockets.push(new URL(message.params.url).pathname);
    if (message.method === 'Network.webSocketFrameSent') {
      try {const frame = JSON.parse(message.params.response.payloadData);
        if (JSON.stringify(frame).includes(boot.session)) report.observedSessionWire.push(frame);
        const selected = (frame.payload?.args?.sessionId ?? frame.payload?.args?.request?.sessionId ?? frame.payload?.args?.request?.address?.sessionId) === boot.session;
        if (frame.method?.startsWith('session/') && selected) report.sessionRequests.push(frame.method);
        if (frame.endpoint?.startsWith('session/') && selected) report.sessionRequests.push(frame.endpoint);
        if (frame.type === 'client-request' && frame.method === boot.endpoint) requests.set(frame.rpcId, frame);
      } catch {}
    }
    if (message.method === 'Network.requestWillBeSent' && message.params.request.method === 'POST') {
      try {
        const wire = JSON.parse(message.params.request.postData);
        if (JSON.stringify(wire).includes(boot.session)) report.observedSessionWire.push(wire);
        if (wire.method?.startsWith('session/') && (wire.payload?.args?.sessionId ?? wire.payload?.args?.request?.sessionId ?? wire.payload?.args?.request?.address?.sessionId) === boot.session) report.sessionRequests.push(wire.method);
        if (wire.method === boot.endpoint) requests.set(message.params.requestId, wire);
      } catch {}
    }
    if (message.method === 'Network.loadingFinished' && requests.has(message.params.requestId)) {
      const request = requests.get(message.params.requestId); requests.delete(message.params.requestId);
      const job = cdp.call('Network.getResponseBody', {requestId: message.params.requestId}).then(result => {
        report.replies.push({request, response: JSON.parse(result.base64Encoded ? Buffer.from(result.body, 'base64').toString('utf8') : result.body)});
      }).catch(error => report.exceptions.push(String(error))).finally(() => replyJobs.delete(job));
      replyJobs.add(job);
    }
    if (message.method === 'Network.webSocketFrameReceived') {
      try {const frame = JSON.parse(message.params.response.payloadData);
        if (frame.type === 'server-response' && requests.has(frame.rpcId)) {
          report.replies.push({request: requests.get(frame.rpcId), response: frame}); requests.delete(frame.rpcId);
        }
      } catch {}
    }
  });
  await cdp.call('Runtime.enable'); await cdp.call('Page.enable'); await cdp.call('Network.enable');
  await cdp.call('Emulation.setDeviceMetricsOverride', {width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false});
  await navigateOriginalPage(cdp, until, boot.url);
  await until(() => count('[class*="frame"]'), 'original shell');
  const notice = '[role="dialog"][aria-label="Internal Testing Notice"]';
  await until(() => count(notice), 'original first-use notice'); await click(notice + ' button');
  await until(async () => !await count(notice), 'notice dismissed');
  report.steps.push('original-shell-and-first-use-notice');
  await deferProviderOnboarding(cdp, until);
  report.steps.push('original-provider-onboarding-deferred-without-credentials');
  await until(() => count('[role="treeitem"]'), 'original sidebar');
  await press(await until(async () => {
    const visible = await cdp.evaluate(`(() => {
      const point=e=>{const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2; return r.width && e.contains(document.elementFromPoint(x,y)) && {x,y};};
      const rows=Array.from(document.querySelectorAll('[role="treeitem"]'));
      const sessions=rows.filter(e=>e.hasAttribute('aria-selected') && point(e));
      if(sessions.length > 1) throw new Error('Expected one visible prepared Session');
      const session=sessions[0];
      if(session) return {session:point(session)};
      const group=rows.find(e=>e.getAttribute('aria-expanded')==='false' && point(e));
      return group && {group:point(group)};
    })()`);
    if (visible?.session) return visible.session;
    if (visible?.group) await press(visible.group);
    return false;
  }, 'persisted Session row'));
  await until(() => cdp.evaluate(`Array.from(document.querySelectorAll('[role="treeitem"][aria-selected="true"]')).some(e=>e.textContent.includes(${JSON.stringify(boot.session)}))`), 'Session selected');
  assert.ok(report.sessionRequests.length > 0, 'original browser selected the persisted identity over Session Remote');
  report.steps.push('original-sidebar-selects-cold-persisted-session');
  await until(() => count('[data-portable-panel]'), 'installed Client activation');
  await click('[data-portable-call]');
  const actual = await until(() => cdp.evaluate('document.querySelector("[data-portable-result]")?.textContent !== "ready" && document.querySelector("[data-portable-result]")?.textContent'), 'Python Host round trip');
  assert.deepEqual(JSON.parse(actual), {ok: true, value: {value: {text: '中文 portable', nested: [null, true, 42]}, runtime: 'Python 3.8.10'}});
  await until(() => report.replies.length === 1, 'actual Remote wire response');
  assert.equal(report.replies[0].response.result.ok, true);
  assert.deepEqual(report.replies[0].request.payload.args.args, {text: '中文 portable', nested: [null, true, 42]});
  assert.ok(report.sockets.includes('/api/remote.mux'));
  assert.deepEqual(report.exceptions, []); assert.deepEqual(report.consoleErrors, []);
  await Promise.all([...replyJobs]);
  report.steps.push('installed-original-evaluator-client-calls-extracted-python-remote');
  const cookies = (await cdp.call('Network.getCookies', {urls: [boot.url]})).cookies;
  browser.kill();
  await until(() => exited(browser), 'abrupt original-browser termination');
  const request = {type: 'client-request', rpcId: 'portable-after-browser-close', method: boot.endpoint,
    payload: {args: {method: 'echo', args: {afterBrowserClose: true}}}};
  const response = await fetch(new URL('/api/' + boot.endpoint, boot.url), {method: 'POST',
    headers: {'Content-Type': 'application/json', Cookie: cookies.map(row => row.name + '=' + row.value).join('; ')},
    body: JSON.stringify(request), signal: AbortSignal.timeout(10000)});
  assert.equal(response.status, 200);
  const healthy = await response.json();
  assert.deepEqual(healthy.result, {ok: true, value: {value: {afterBrowserClose: true}, runtime: 'Python 3.8.10'}});
  assert.equal(host.exitCode, null, 'Host remains alive after browser disconnect');
  report.steps.push('abrupt-browser-close-retains-same-host-and-installed-remote-service');
  report.passed = true;
} catch (error) {
  report.failure = String(error.stack ?? error);
  if (cdp && browser && !exited(browser)) {try {report.pageText = await cdp.evaluate('document.body.innerText');
    report.treeItems = await cdp.evaluate("Array.from(document.querySelectorAll('[role=treeitem]')).map(e=>({text:e.textContent,expanded:e.getAttribute('aria-expanded'),selected:e.getAttribute('aria-selected')}))");
    report.bundleProbe = await cdp.evaluate(`(async()=>{const r=await fetch(${JSON.stringify(report.installedClientEntry?.url)});const text=await r.text();return {status:r.status,hasPanel:text.includes('data-portable-panel'),head:text.slice(0,200),tail:text.slice(-200),loaderKeys:Object.keys(window.__ModuleLoader__||{})};})()`);
  } catch {}}
} finally {
  try {await closeOriginalBrowser(cdp, browser, until);}
  catch (error) {report.passed = false; report.browserTeardownFailure = String(error.stack ?? error);}
  if (host && host.exitCode === null) {
    host.stdin.end(JSON.stringify({command: 'stop'}) + '\n');
    try {await until(() => host.exitCode !== null, 'Host shutdown', 15000);} catch {host.kill(); report.passed = false;}
  }
  cdp?.socket.close();
  browser?.kill();
  report.hostErrors = hostErrors.replace(/token=[^\s]+/g, 'token=[redacted]');
  report.hostExitCode = host?.exitCode;
  report.browserExitCode = browser?.exitCode;
  report.browserSignalCode = browser?.signalCode;
  if (report.passed && (report.hostErrors || report.hostExitCode !== 0)) {report.passed = false; report.failure = 'Host teardown failed';}
  assert.equal(resolve(dirname(privateBrowser)), resolve(tmpdir()));
  assert.ok(basename(privateBrowser).startsWith('dsh-portable-'));
  try {await rm(privateBrowser, {recursive: true, force: true, maxRetries: 5, retryDelay: 100});}
  catch (error) {report.passed = false; report.cleanupFailure = String(error.stack ?? error);}
  await writeFile(resolve(options.output), JSON.stringify(report, null, 2) + '\n', 'utf8');
}
console.log(JSON.stringify({passed: report.passed, steps: report.steps.length, failure: report.failure}));
if (!report.passed) process.exitCode = 1;
