/** Development-only actual Chromium/original frontend/native Python oracle.
 * Node and Chromium are test tools, never dependencies of the Python Host.
 * No Playwright dependency, browser source edits, mock routes or hidden APIs.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, args) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), args[i + 1]]);
  return pairs;
}, []));
if (!options.browser || !options.output) throw new Error('Use --browser <Chromium executable> --output <report.json>');
const output = resolve(options.output);
await mkdir(dirname(output), { recursive: true });
const privateBrowser = await mkdtemp(join(tmpdir(), 'dsh-cdp-'));
const delay = ms => new Promise(done => setTimeout(done, ms));
const report = { kind: 'actual-original-browser/native-python-host', steps: [], errors: [], consoleErrors: [], requests: [], webSockets: [], remoteCalls: {} };
let host, browser, cdp, nextHost = 1;
const pendingHost = new Map();
let hostLog = '';
let hostErrors = '';
let browserErrors = '';

class CDP {
  constructor(socket) {
    this.socket = socket; this.next = 1; this.pending = new Map(); this.listeners = [];
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const call = this.pending.get(message.id);
        if (call) { this.pending.delete(message.id); clearTimeout(call.timer); message.error ? call.reject(new Error(JSON.stringify(message.error))) : call.resolve(message.result); }
      } else for (const listener of this.listeners) listener(message);
    });
  }
  async call(method, params = {}) {
    const id = this.next++;
    return await new Promise((resolveCall, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 15000);
      this.pending.set(id, { resolve: resolveCall, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}

async function until(read, description, timeout = 15000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) { last = await read(); if (last) return last; await delay(100); }
  throw new Error(`Timed out: ${description}; last=${JSON.stringify(last)}`);
}
async function command(command, value = {}) {
  const id = nextHost++;
  return await new Promise((resolveCommand, reject) => {
    const timer = setTimeout(() => { pendingHost.delete(id); reject(new Error(`Host timeout: ${command}`)); }, 20000);
    pendingHost.set(id, { resolve: resolveCommand, reject, timer });
    host.stdin.write(JSON.stringify({ id, command, ...value }) + '\n');
  });
}
const count = selector => cdp.evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
const attribute = (selector, name) => cdp.evaluate(`document.querySelector(${JSON.stringify(selector)})?.getAttribute(${JSON.stringify(name)})`);
async function click(selector) {
  await until(() => count(selector), selector);
  const point = await until(() => cdp.evaluate(`(() => { const e=document.querySelector(${JSON.stringify(selector)}); if(!e) return false; e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2; return r.width && r.height && e.contains(document.elementFromPoint(x,y)) && {x,y,disabled:e.disabled}; })()`), `visible unobstructed ${selector}`);
  assert.equal(point.disabled, false, `Disabled control: ${selector}`);
  await cdp.call('Input.dispatchMouseEvent', { type: 'mousePressed', x: point.x, y: point.y, button: 'left', clickCount: 1 });
  await cdp.call('Input.dispatchMouseEvent', { type: 'mouseReleased', x: point.x, y: point.y, button: 'left', clickCount: 1 });
}
async function panel() {
  if (!await count('[data-cordis-panel]')) await click('[data-cordis-badge]');
}
function codeFor(version, failure = false) {
  return {
    host: `def plugin(ctx):\n    ctx.provide("nativeBrowserProbe", ${JSON.stringify(version)})\n    harness.handle("echo", lambda value: {"version": ${JSON.stringify(version)}, "value": value})\n`,
    client: failure ? 'return { apply(ctx) { throw new Error("native browser fixture client failure") } }' :
      `return { inject: ["slots"], apply(ctx) { function Probe() { const [result,setResult] = React.useState("ready"); return React.createElement("div", { "data-native-browser-probe": ${JSON.stringify(version)}, style: { position: "fixed", top: 20, left: 800, zIndex: 999 } }, React.createElement("button", { "data-native-browser-echo": true, onClick: async () => { try { setResult(JSON.stringify(await host.call("echo", { nested: [null, true, "中文", 42] }))) } catch (e) { setResult(String(e)) } } }, "Call Python Host"), React.createElement("output", { "data-native-browser-result": true }, result)) } ctx.slots.register({ name: "shell.overlay", id: "native-browser-probe" }, Probe) } }`,
  };
}
async function active(version) {
  await until(() => count(`[data-native-browser-probe="${version}"]`), `actual Client ${version}`);
  return await until(async () => { const s = await command('snapshot'); return s.inventory[0]?.latestRun?.status === 'running' && s.probe === version && s; }, `Host committed ${version}`);
}
async function echo(version) {
  await click('[data-native-browser-echo]');
  const value = await until(() => cdp.evaluate('document.querySelector("[data-native-browser-result]")?.textContent !== "ready" && document.querySelector("[data-native-browser-result]")?.textContent'), 'Client/Host JSON round trip');
  assert.deepEqual(JSON.parse(value), { version, value: { nested: [null, true, '中文', 42] } });
  report.steps.push({ step: `original-client-host-call-json-${version}`, passed: true });
}

try {
  const inputs = JSON.parse(await readFile(join(root, 'scripts/frontend-inputs.json'), 'utf8'));
  const mismatches = [];
  for (const row of inputs.files) {
    if (createHash('sha256').update(await readFile(join(root, row.path))).digest('hex') !== row.sha256) mismatches.push(row.path);
  }
  assert.deepEqual(mismatches, [], 'Pinned frontend input bytes changed');
  report.target_upstream = inputs.target_upstream;
  report.frontendInputCount = inputs.files.length;
  report.inputSha256 = {};
  for (const path of ['scripts/native_web_browser_oracle.mjs', 'scripts/native_web_host_fixture.py',
    'scripts/frontend-inputs.json', 'dsh/extensions/host_runner.py', 'dsh/extensions/cordis_runner_state.py',
    'dsh/extensions/cordis_guard.py', 'dsh/typert/dispatch.py', 'dsh/host/connection/canonical.py',
    'dsh/host/client_modules/loader_registry.py', 'dsh/boot/profile_boot.py']) {
    report.inputSha256[path] = createHash('sha256').update(await readFile(join(root, path))).digest('hex');
  }
  let readyResolve, readyReject;
  const ready = new Promise((yes, no) => { readyResolve = yes; readyReject = no; });
  host = spawn(join(root, '.venv/Scripts/python.exe'), ['-u', join(root, 'scripts/native_web_host_fixture.py')], { cwd: root, windowsHide: true });
  host.stderr.on('data', data => { hostErrors += data; });
  host.on('error', readyReject);
  host.on('exit', code => { readyReject(new Error(`Host exited: ${code}; ${hostErrors.slice(-2500)}`)); for (const call of pendingHost.values()) { clearTimeout(call.timer); call.reject(new Error(`Host exited ${code}`)); } pendingHost.clear(); });
  createInterface({ input: host.stdout }).on('line', line => {
    if (!line.startsWith('DSH_PROBE ')) { hostLog += line + '\n'; return; }
    const value = JSON.parse(line.slice(10));
    if (value.ready) readyResolve(value);
    else { const call = pendingHost.get(value.id); if (call) { pendingHost.delete(value.id); clearTimeout(call.timer); value.ok ? call.resolve(value.value) : call.reject(new Error(value.error)); } }
  });
  const timeout = setTimeout(() => readyReject(new Error(`Host did not boot; ${hostErrors.slice(-2500)}`)), 60000);
  const boot = await ready.finally(() => clearTimeout(timeout));
  report.python = boot.python;
  assert.equal(boot.python, '3.8.10');
  report.clientArtifacts = [];
  for (const artifact of boot.clientArtifacts) {
    const bytes = await readFile(artifact.path);
    const mapBytes = await readFile(artifact.path + '.map');
    const map = JSON.parse(mapBytes);
    const sources = [];
    assert.equal(map.sources.length, map.sourcesContent.length, 'Client map must retain source content');
    for (let i = 0; i < map.sources.length; i++) {
      const name = map.sources[i].replaceAll('\\', '/');
      const packageStart = name.indexOf('packages/');
      if (packageStart < 0) {
        assert.ok(name.includes('node_modules/') || name.includes('vendor/'), `Unbound source map path: ${name}`);
        sources.push({ vendor: name, sourceSha256: createHash('sha256').update(map.sourcesContent[i]).digest('hex') });
        continue;
      }
      const path = name.slice(packageStart);
      let source;
      let generated = false;
      try { source = await readFile(join(root, 'reference', path), 'utf8'); }
      catch (error) {
        if (error.code !== 'ENOENT' || !path.includes('/lib/')) throw error;
        source = await readFile(join(root, path), 'utf8');
        generated = true;
      }
      assert.equal(map.sourcesContent[i].replaceAll('\r\n', '\n'), source.replaceAll('\r\n', '\n'), `Client source map differs from pinned original: ${path}`);
      sources.push(generated ? { generated: path, sourceSha256: createHash('sha256').update(source).digest('hex') } : path);
    }
    report.clientArtifacts.push({ name: artifact.name, path: artifact.path.replace(root, '[workspace]'), sha256: createHash('sha256').update(bytes).digest('hex'), sourceMapSha256: createHash('sha256').update(mapBytes).digest('hex'), sources });
  }
  browser = spawn(resolve(options.browser), ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0', `--user-data-dir=${privateBrowser}`, '--lang=en-US', 'about:blank'], { windowsHide: true });
  browser.stderr.on('data', data => { browserErrors += data; });
  browser.on('error', error => { browserErrors += String(error); });
  const port = await until(async () => { try { return (await readFile(join(privateBrowser, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return false; } }, 'Chromium DevTools port');
  const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(row => row.type === 'page');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((yes, no) => { socket.addEventListener('open', yes, { once: true }); socket.addEventListener('error', no, { once: true }); });
  cdp = new CDP(socket);
  report.browser = await cdp.call('Browser.getVersion');
  cdp.listeners.push(message => {
    if (message.method === 'Runtime.exceptionThrown') report.errors.push(message.params.exceptionDetails);
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') report.consoleErrors.push(message.params.args.map(value => value.value ?? value.description));
    if (message.method === 'Network.responseReceived' && message.params.response.status >= 400) report.requests.push({ url: message.params.response.url.replace(/\?.*/, '?[redacted]'), status: message.params.response.status });
    if (message.method === 'Network.webSocketCreated') report.webSockets.push(new URL(message.params.url).pathname);
    // Original Connection sends unary RPCs over POST; remote.mux owns streams.
    if (message.method === 'Network.requestWillBeSent' && message.params.request.method === 'POST') {
      const path = new URL(message.params.request.url).pathname;
      for (const method of ['runHostHalf', 'getClientCode', 'resolveRequestRun', 'settleUserRun', 'invoke', 'stopFromPanel', 'undefineFromPanel']) {
        if (path.endsWith(`/dynamicCordisRunner/${method}`)) report.remoteCalls[method] = (report.remoteCalls[method] ?? 0) + 1;
      }
    }
    if (message.method === 'Network.webSocketFrameSent') {
      const frame = message.params.response;
      const payload = frame.opcode === 2 ? Buffer.from(frame.payloadData, 'base64').toString('utf8') : frame.payloadData;
      for (const method of ['runHostHalf', 'getClientCode', 'resolveRequestRun', 'settleUserRun', 'invoke', 'stopFromPanel', 'undefineFromPanel']) {
        if (payload.includes(method)) report.remoteCalls[method] = (report.remoteCalls[method] ?? 0) + 1;
      }
    }
  });
  await cdp.call('Runtime.enable'); await cdp.call('Page.enable'); await cdp.call('Network.enable');
  await cdp.call('Emulation.setDeviceMetricsOverride', { width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.call('Emulation.setLocaleOverride', { locale: 'en-US' });
  await cdp.call('Page.navigate', { url: boot.url });
  await until(() => count('[class*="frame"]'), 'original application frame', 30000);
  report.steps.push({ step: 'original-frontend-boot', passed: true });
  report.initialText = await cdp.evaluate('document.body.innerText');
  report.initialControls = await cdp.evaluate("Array.from(document.querySelectorAll('button,input,[role=dialog]')).map(e=>({tag:e.tagName,text:e.textContent,label:e.getAttribute('aria-label'),role:e.getAttribute('role')}))");
  await until(() => count('[role="dialog"][aria-label="Internal Testing Notice"]'), 'onboarding notice');
  await click('[role="dialog"][aria-label="Internal Testing Notice"] button');
  await until(async () => await count('[role="dialog"][aria-label="Internal Testing Notice"]') === 0, 'onboarding dismissed');
  report.steps.push({ step: 'original-onboarding-settings-remote', passed: true });
  const defined = await command('define', { plugin: { kind: 'new', idPrefix: 'probe' }, code: codeFor('v1') });
  report.defined = defined;
  await command('request-run', defined);
  await until(() => count('[data-cordis-approve]'), 'original approval control');
  assert.equal(await count('[data-native-browser-probe]'), 0);
  assert.equal((await command('snapshot')).probe, null);
  report.steps.push({ step: 'no-host-or-client-before-approval', passed: true });
  await click('[data-cordis-approve]');
  const running = await active('v1');
  assert.equal(running.probe, 'v1'); assert.equal(running.pending.length, 0);
  report.steps.push({ step: 'original-ui-approval-native-host-client-running', passed: true, snapshot: running });
  await echo('v1');
  const updated = await command('define', { plugin: { kind: 'existing', pluginId: defined.pluginId }, code: codeFor('v2') });
  const updateRequest = await command('request-run', { ...updated, mode: 'update' });
  assert.equal(updateRequest.status, 'awaiting-approval');
  await until(() => count('[data-cordis-approve-plugin]'), 'version two approval');
  assert.equal((await command('snapshot')).probe, 'v1');
  assert.equal(await count('[data-native-browser-probe="v1"]'), 1);
  await click('[data-cordis-approve-plugin]');
  const v2 = await active('v2');
  assert.equal(v2.inventory[0].currentPackageId, updated.packageId);
  assert.equal(await count('[data-native-browser-probe="v1"]'), 0);
  report.steps.push({ step: 'original-ui-approve-future-update-replaces-both-halves', passed: true, snapshot: v2 });
  await echo('v2');

  const failed = await command('define', { plugin: { kind: 'existing', pluginId: defined.pluginId }, code: codeFor('broken', true) });
  const failureRequest = await command('request-run', { ...failed, mode: 'update' });
  assert.equal(failureRequest.status, 'starting');
  const failedHost = await until(async () => { const s = await command('snapshot'); return s.inventory[0]?.latestRun?.status === 'failed' && !s.pending.length && s; }, 'Client apply failure returned to Host');
  assert.equal(failedHost.inventory[0].currentPackageId, updated.packageId);
  assert.equal(failedHost.inventory[0].nextPackageId, failed.packageId);
  assert.equal(failedHost.probe, null);
  assert.equal(failedHost.inventory[0].activeRun, undefined);
  await until(async () => await count('[data-native-browser-probe]') === 0, 'failed update cleaned Client');
  await panel();
  await until(() => attribute('[data-cordis-row]', 'data-cordis-status').then(value => value === 'failed'), 'original UI failure status');
  assert.match(await cdp.evaluate('document.querySelector("[data-cordis-panel]").innerText'), /native browser fixture client failure/);
  report.steps.push({ step: 'client-failure-retracts-host-keeps-version-pointers-and-ui-diagnostic', passed: true, snapshot: failedHost });

  const recovery = await command('define', { plugin: { kind: 'existing', pluginId: defined.pluginId }, code: codeFor('v4') });
  await command('request-run', { ...recovery, mode: 'update' });
  const v4 = await active('v4');
  assert.equal(v4.inventory[0].currentPackageId, recovery.packageId);
  report.steps.push({ step: 'same-plugin-new-package-recovers-after-client-failure', passed: true, snapshot: v4 });
  await echo('v4');

  await cdp.call('Page.reload');
  await until(() => count('[class*="frame"]'), 'refreshed original app');
  await until(() => count('[data-cordis-badge]'), 'refreshed host inventory');
  await panel();
  await until(() => attribute('[data-cordis-row]', 'data-cordis-status').then(value => value === 'client-pending'), 'page-local Client pending');
  assert.equal(await count('[data-native-browser-probe]'), 0);
  assert.equal((await command('snapshot')).probe, 'v4');
  report.steps.push({ step: 'refresh-preserves-host-without-auto-running-client', passed: true });
  await click('[data-cordis-switch="run"]');
  const attached = await active('v4');
  assert.equal(attached.inventory[0].activeRun.pluginRunId, v4.inventory[0].activeRun.pluginRunId);
  report.steps.push({ step: 'original-ui-reattaches-client-to-existing-host-run', passed: true, snapshot: attached });
  await echo('v4');

  await panel(); await click('[data-cordis-switch="stop"]');
  await until(async () => await count('[data-native-browser-probe]') === 0, 'Client removal');
  const stopped = await command('snapshot');
  assert.equal(stopped.probe, null); assert.equal(stopped.inventory[0].latestRun.status, 'stopped');
  report.steps.push({ step: 'original-ui-stop-releases-both-halves', passed: true, snapshot: stopped });
  await click('[data-cordis-switch="run"]');
  const restarted = await active('v4');
  assert.notEqual(restarted.inventory[0].activeRun.pluginRunId, attached.inventory[0].activeRun.pluginRunId);
  report.steps.push({ step: 'original-ui-restart-allocates-fresh-host-run', passed: true, snapshot: restarted });
  await panel();
  await click('[data-cordis-remove]');
  await until(async () => (await command('snapshot')).inventory.length === 0, 'definition removed');
  await until(async () => await count('[data-native-browser-probe]') === 0, 'active definition Client removed');
  assert.equal((await command('snapshot')).probe, null);
  report.steps.push({ step: 'original-ui-remove-definition', passed: true });

  const declined = await command('define', { plugin: { kind: 'new', idPrefix: 'deny' }, code: codeFor('declined') });
  await command('request-run', declined);
  await click('[data-cordis-decline]');
  const rejected = await until(async () => { const s = await command('snapshot'); return s.inventory[0]?.latestRun?.status === 'rejected' && s; }, 'original UI rejection');
  assert.equal(await count('[data-native-browser-probe]'), 0); assert.equal(rejected.probe, null); assert.equal(rejected.pending.length, 0);
  report.steps.push({ step: 'original-ui-decline-executes-neither-half', passed: true, snapshot: rejected });
  assert.deepEqual(report.errors, []); assert.deepEqual(report.requests, []);
  assert.equal(report.consoleErrors.length, 1, 'Only the deliberately failed Client may log an error');
  assert.equal(report.consoleErrors[0][0], '[cordis-client-runner] Client activation probe-1/pkg-3 (run-3) failed:');
  assert.match(report.consoleErrors[0][1], /^Error: failed to apply loader entry [a-f0-9]+ \(dyn\/probe-1\): native browser fixture client failure\n/);
  report.expectedConsoleError = report.consoleErrors[0];
  assert.ok(report.webSockets.includes('/api/remote.mux'));
  for (const method of ['runHostHalf', 'getClientCode', 'resolveRequestRun', 'settleUserRun', 'invoke', 'stopFromPanel', 'undefineFromPanel']) assert.ok(report.remoteCalls[method], `Actual browser did not send ${method}`);
  for (const [path, hash] of Object.entries(report.inputSha256)) assert.equal(createHash('sha256').update(await readFile(join(root, path))).digest('hex'), hash, `Probe input changed during execution: ${path}`);
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = String(error.stack ?? error);
  if (host?.exitCode === null) { try { report.failureHost = await command('snapshot'); } catch {} }
  if (cdp) {
    try {
      if (await count('[data-cordis-badge]') && !await count('[data-cordis-panel]')) await panel();
      report.failureText = await cdp.evaluate('document.body.innerText');
      report.failureControls = await cdp.evaluate("Array.from(document.querySelectorAll('button,input,[role=dialog]')).map(e=>({tag:e.tagName,text:e.textContent,label:e.getAttribute('aria-label'),role:e.getAttribute('role')}))");
      const screenshot = await cdp.call('Page.captureScreenshot');
      await writeFile(output + '.png', Buffer.from(screenshot.data, 'base64'));
    } catch (captureError) { report.captureError = String(captureError); }
  }
} finally {
  if (host?.exitCode === null) { try { await command('shutdown'); await until(() => host.exitCode !== null, 'host orderly shutdown'); } catch { host.kill(); } }
  if (cdp) cdp.socket.close();
  if (browser?.exitCode === null) { browser.kill(); await until(() => browser.exitCode !== null, 'test browser exit').catch(() => {}); }
  // Never write launch-token-bearing stdout to evidence.
  report.hostErrors = hostErrors.replace(/token=[^\s]+/g, 'token=[redacted]');
  report.browserErrors = browserErrors;
  assert.equal(resolve(dirname(privateBrowser)), resolve(tmpdir()));
  assert.ok(basename(privateBrowser).startsWith('dsh-cdp-'));
  await rm(privateBrowser, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  await writeFile(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
}
console.log(JSON.stringify({ passed: report.passed, steps: report.steps.length, output, failure: report.failure }));
if (!report.passed) process.exitCode = 1;
