/** Real original-browser installed Python/Client/Remote package journey. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { credentialFreeEnvironment, deferProviderOnboarding } from './browser_onboarding.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, args) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), args[i + 1]]); return pairs;
}, []));
if (!options.browser || !options.output) throw new Error('Use --browser <Chromium> --output <report.json>');
const output = resolve(options.output);
await mkdir(dirname(output), { recursive: true });
const privateBrowser = await mkdtemp(join(tmpdir(), 'dsh-web-package-cdp-'));
const report = { kind: 'original-browser/installed-python-web-package', steps: [], errors: [], consoleErrors: [], requests: [], replies: [], sockets: [] };
let packageName = '@example/python-web-echo', rpcEndpoint = 'pythonWebEcho/echo';
let browser, host, cdp, hostErrors = '', nextCommand = 1;
const pending = new Map();
const replyJobs = new Set();
const finiteRequests = new Set();
let networkChanged = Date.now();
const delay = ms => new Promise(done => setTimeout(done, ms));
async function until(read, label, timeout = 20000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const value = await read(); if (value) return value; await delay(100); }
  throw new Error('Timed out: ' + label);
}
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
    return await new Promise((yes, no) => {
      const timer = setTimeout(() => { this.pending.delete(id); no(new Error('CDP timeout: ' + method)); }, 15000);
      this.pending.set(id, { resolve: yes, reject: no, timer }); this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
}
async function command(command) {
  const id = nextCommand++;
  return await new Promise((yes, no) => {
    const timer = setTimeout(() => { pending.delete(id); no(new Error('Host timeout: ' + command)); }, 30000);
    pending.set(id, { yes, no, timer }); host.stdin.write(JSON.stringify({ id, command }) + '\n');
  });
}
const count = selector => cdp.evaluate(`document.querySelectorAll(${JSON.stringify(selector)}).length`);
async function settleNetwork() {
  await until(() => finiteRequests.size === 0 && Date.now() - networkChanged >= 500,
    'finite browser requests settled before controlled transition');
}
async function onboarding(required = false) {
  await until(() => count('[class*="frame"]'), 'application shell after navigation');
  await settleNetwork();
  const deferred = await deferProviderOnboarding(cdp, until, required);
  report.providerOnboardingChecks = (report.providerOnboardingChecks ?? 0) + 1;
  report.providerOnboardingDeferrals = (report.providerOnboardingDeferrals ?? 0) + Number(deferred);
}
async function closePage() {
  await settleNetwork();
  await cdp.call('Page.navigate', {url: 'about:blank'});
  await until(() => cdp.evaluate('location.href === "about:blank"'), 'close page before Host transition');
}
async function reloadPage() {
  await settleNetwork();
  await cdp.call('Page.reload', {ignoreCache: true});
  await onboarding();
}
async function click(selector) {
  const point = await until(() => cdp.evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); if(!e) return false; const r=e.getBoundingClientRect(),x=r.x+r.width/2,y=r.y+r.height/2; return r.width && e.contains(document.elementFromPoint(x,y)) && {x,y};})()`), selector);
  await cdp.call('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
  await cdp.call('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
}
async function open(boot, present = true) {
  await cdp.call('Page.navigate', { url: boot.url });
  await until(() => count('[class*="frame"]'), 'original application shell', 30000);
  // Dismiss the original first-use notice through its actual visible control.
  const notice = '[role="dialog"][aria-label="Internal Testing Notice"]';
  if (!report.noticeDismissed) await until(() => count(notice), 'original first-use notice');
  if (await count(notice)) {
    await click(notice + ' button');
    await until(async () => !await count(notice), 'notice dismissed');
    report.noticeDismissed = true;
  }
  await onboarding(!report.providerOnboardingChecks);
  if (present) await until(() => count('[data-python-web-echo]'), 'installed Client automatic activation');
  else { await delay(500); assert.equal(await count('[data-python-web-echo]'), 0); }
}
async function echo(version, calls, agentId) {
  await click('[data-python-web-echo-call]');
  const value = await until(() => cdp.evaluate(`(() => {try {const text=document.querySelector('[data-python-web-echo-result]')?.textContent; const value=JSON.parse(text); return value.ok && value.value.calls === ${calls} && value.value.version === ${JSON.stringify(version)} && text;} catch {return false;}})()`), 'Client Remote reply');
  assert.deepEqual(JSON.parse(value), { ok: true, value: { text: 'Python Web echo: 中文 portable', calls, version } });
  const state = await command('snapshot');
  assert.equal(agentId === undefined ? state.calls : state.sessionCalls[agentId], calls);
  report.steps.push({ step: `original-client-strict-remote-${version}-call-${calls}`, passed: true });
}
async function selectSession(agentId, present = true) {
  await until(() => count('[role="treeitem"]'), 'original sidebar rows ready');
  if (await count('[role="treeitem"][aria-expanded="false"]')) await click('[role="treeitem"][aria-expanded="false"]');
  const point = await until(() => cdp.evaluate(`(() => {
    const row = Array.from(document.querySelectorAll('[role="treeitem"]')).find(e => e.textContent.includes(${JSON.stringify(agentId)}));
    if (!row) return false; const r = row.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
    return r.width && row.contains(document.elementFromPoint(x,y)) && {x,y};
  })()`), 'original sidebar Session ' + agentId);
  await cdp.call('Input.dispatchMouseEvent', {type: 'mousePressed', ...point, button: 'left', clickCount: 1});
  await cdp.call('Input.dispatchMouseEvent', {type: 'mouseReleased', ...point, button: 'left', clickCount: 1});
  await until(() => cdp.evaluate(`Array.from(document.querySelectorAll('[role="treeitem"][aria-selected="true"]')).some(e => e.textContent.includes(${JSON.stringify(agentId)}))`), 'original Session selected');
  if (present) await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'Session Client activation');
  else await until(async () => !await count('[data-python-web-echo]'), 'Session Client absent');
}
async function sessionJourney(boot) {
  const a = 'python-session-a', b = 'python-session-b', shared = 'python-session-shared', plain = 'python-session-plain';
  assert.equal(boot.sourceAtRoot, false);
  await open(boot, false);
  await selectSession(a); await echo('1.0.0', 1, a); await echo('1.0.0', 2, a);
  await selectSession(b); await echo('1.0.0', 1, b);
  await selectSession(shared); await echo('1.0.0', 3, shared);
  await selectSession(plain, false);
  assert.equal(await count('style[data-dyn^="python-export-"]'), 0);
  report.steps.push({step: 'original-sidebar-independent-and-shared-presets-no-plain-client-no-root-source', passed: true});
  await command('hold-availability');
  await selectSession(a, false);
  await until(() => command('availability-waiting'), 'actual Agent lookup availability request held');
  await selectSession(b);
  assert.equal(await command('availability-waiting'), true);
  await command('release-availability');
  await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'latest selection wins delayed availability');
  await echo('1.0.0', 2, b);
  assert.equal((await command('snapshot')).sessionCalls[a], 3);
  assert.equal(await count('style[data-dyn^="python-export-"]'), 1);
  report.steps.push({step: 'late-availability-cannot-mount-client-for-old-selection', passed: true});
  await selectSession(a); await echo('1.0.0', 4, a);
  const timeOrigin = await cdp.evaluate('performance.timeOrigin');
  for (const [operation, calls] of [['rebuild-client', 5], ['restore-client', 6]]) {
    await command(operation);
    await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'Session Client HMR');
    assert.equal(await cdp.evaluate('performance.timeOrigin'), timeOrigin);
    assert.equal(await count('style[data-dyn^="python-export-"]'), 1);
    await echo('1.0.0', calls, a);
  }
  report.steps.push({step: 'session-client-real-hmr-preserves-preset-host-and-disposes-old-fiber', passed: true});
  await command('unload-session');
  await click('[data-python-web-echo-call]');
  await until(() => cdp.evaluate(`(() => {try {const v=JSON.parse(document.querySelector('[data-python-web-echo-result]')?.textContent); return v.ok === false && /not mounted/.test(v.error.message);} catch {return false;}})()`), 'unloaded preset handler rejects retained Client');
  await selectSession(plain, false); await selectSession(shared, false);
  await selectSession(b); await echo('1.0.0', 3, b);
  report.steps.push({step: 'preset-unload-affects-shared-members-and-preserves-other-preset', passed: true});
  await reloadPage();
  await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'restored selected Session Client');
  await echo('1.0.0', 4, b);
  report.steps.push({step: 'page-reload-restores-selected-session-with-preset-host-retained', passed: true});
  await command('unload');
  await click('[data-python-web-echo-call]');
  await until(() => cdp.evaluate(`(() => {try {const v=JSON.parse(document.querySelector('[data-python-web-echo-result]')?.textContent); return v.ok === false && /strict definition was withdrawn/.test(v.error.message);} catch {return false;}})()`), 'withdrawn Session bridge rejects retained Client');
  await reloadPage();
  await until(async () => !await count('[data-python-web-echo]') && await count('[class*="frame"]'), 'no Session Client after bridge graph withdrawal');
  report.steps.push({step: 'bridge-withdrawal-forbids-src-fallback-and-reload-removes-client', passed: true});
  for (const [operation, version] of [['restart', '1.0.0'], ['upgrade', '2.0.0'], ['rollback', '1.0.0']]) {
    await closePage();
    const next = await command(operation);
    assert.equal(next.sourceAtRoot, false);
    assert.equal(next.sessionCalls[a], 0); assert.equal(next.sessionCalls[b], 0);
    await open(next, false);
    await selectSession(a); await echo(version, 1, a);
    report.steps.push({step: operation + '-restores-installed-session-client-source', passed: true});
  }
  await selectSession(plain, false);
  await closePage();
  const removed = await command('remove');
  assert.equal(removed.graph.entries.some(row => row.id === packageName), false);
  await open(removed, false);
  report.steps.push({step: 'remove-with-user-presets-preserved-no-installed-client', passed: true});
}
async function transition(operation, version, present = true) {
  await closePage();
  const boot = await command(operation);
  assert.equal(boot.calls, present ? 0 : null);
  assert.equal(boot.descriptor, present);
  assert.equal(boot.graph.entries.some(row => row.id === packageName), present);
  await open(boot, present);
  if (present) await echo(version, 1);
  report.steps.push({ step: operation + '-from-installed-package', passed: true });
}
try {
  const inputs = JSON.parse(await readFile(join(root, 'scripts/frontend-inputs.json'), 'utf8'));
  for (const row of inputs.files) assert.equal(createHash('sha256').update(await readFile(join(root, row.path))).digest('hex'), row.sha256, row.path);
  report.target_upstream = inputs.target_upstream;
  report.frontendInputCount = inputs.files.length;
  report.inputSha256 = {};
  for (const path of ['scripts/python_web_plugin_browser_oracle.mjs', 'scripts/browser_onboarding.mjs', 'scripts/python_web_plugin_host_fixture.py',
    'dsh/boot/python_web_artifacts.py', 'dsh/plugin_api.py', 'dsh/plugin_remote.py',
    'dsh/boot/python_package.py', 'dsh/boot/python_plugin_export.py', 'dsh/boot/python_plugins.py',
    'scripts/build_python_web_example.py', 'tests/test_python_web_plugin.py',
    'dsh/boot/python_client_build.py', 'dsh/extensions/packaged_client.js',
    'dsh/extensions/packaged_host.py', 'scripts/python_export_client_fixture.py',
    'tests/test_python_client_build.py',
    'examples/python-web-echo/package.json', 'examples/python-web-echo/python/web_echo/plugin.py',
    'examples/python-web-echo/client/client.js', 'examples/python-web-echo/client/client.js.map',
    'examples/python-web-echo/remote/typert.py', 'examples/python-web-echo/remote/contract.json']) {
    report.inputSha256[path] = createHash('sha256').update(await readFile(join(root, path))).digest('hex');
  }
  let readyYes, readyNo;
  const ready = new Promise((yes, no) => { readyYes = yes; readyNo = no; });
  const readyTimer = setTimeout(() => readyNo(new Error('Host startup timed out')), 30000);
  host = spawn(join(root, '.venv/Scripts/python.exe'), ['-u', join(root, 'scripts/python_web_plugin_host_fixture.py'), ...(options.exported ? ['--exported'] : []), ...(options.session ? ['--session'] : [])], { cwd: root, windowsHide: true, env: credentialFreeEnvironment(process.env) });
  report.credentialFreeHost = true;
  host.stderr.on('data', data => { hostErrors += data; });
  host.on('error', readyNo);
  host.on('exit', code => { readyNo(new Error('Host exited: ' + code)); });
  createInterface({ input: host.stdout }).on('line', line => {
    if (!line.startsWith('DSH_WEB_PACKAGE ')) return;
    const message = JSON.parse(line.slice('DSH_WEB_PACKAGE '.length));
    if (message.ready) { readyYes(message.value); return; }
    const task = pending.get(message.id);
    if (task) { pending.delete(message.id); clearTimeout(task.timer); message.ok ? task.yes(message.value) : task.no(new Error(message.error)); }
  });
  const boot = await ready.finally(() => clearTimeout(readyTimer));
  report.python = boot.python;
  packageName = boot.name; rpcEndpoint = boot.endpoint; report.exported = boot.exported; report.session = boot.session;
  assert.equal(boot.python, '3.8.10'); assert.equal(boot.descriptor, true); assert.equal(boot.calls, 0);
  browser = spawn(resolve(options.browser), ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0', `--user-data-dir=${privateBrowser}`, '--lang=en-US', 'about:blank'], { windowsHide: true });
  const port = await until(async () => { try { return (await readFile(join(privateBrowser, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; } catch { return false; } }, 'browser port');
  const target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(row => row.type === 'page');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((yes, no) => { socket.addEventListener('open', yes, { once: true }); socket.addEventListener('error', no, { once: true }); });
  cdp = new CDP(socket);
  const requests = new Map();
  cdp.listeners.push(message => {
    if (message.method === 'Network.requestWillBeSent') {
      const params = message.params;
      if (!['EventSource', 'WebSocket'].includes(params.type) && !new URL(params.request.url).pathname.endsWith('/plugins/events')) {
        finiteRequests.add(params.requestId);
        networkChanged = Date.now();
      }
    }
    if (['Network.loadingFinished', 'Network.loadingFailed'].includes(message.method)
        && finiteRequests.delete(message.params.requestId)) networkChanged = Date.now();
    if (message.method === 'Runtime.exceptionThrown') report.errors.push(message.params.exceptionDetails);
    if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') report.consoleErrors.push(message.params.args.map(value => value.value ?? value.description));
    if (message.method === 'Network.webSocketCreated') report.sockets.push(new URL(message.params.url).pathname);
    if (message.method === 'Network.webSocketFrameSent') {
      try {
        const frame = JSON.parse(message.params.response.payloadData);
        if (frame.type === 'client-request' && frame.method === rpcEndpoint) requests.set(frame.rpcId, frame);
      } catch {}
    }
    if (message.method === 'Network.webSocketFrameReceived') {
      try {
        const frame = JSON.parse(message.params.response.payloadData);
        if (frame.type === 'server-response' && requests.has(frame.rpcId)) {
          report.replies.push({request: requests.get(frame.rpcId), response: frame}); requests.delete(frame.rpcId);
        }
      } catch {}
    }
    if (message.method === 'Network.requestWillBeSent' && message.params.request.method === 'POST' && new URL(message.params.request.url).pathname.endsWith('/' + rpcEndpoint)) {
      const args = JSON.parse(message.params.request.postData);
      requests.set(message.params.requestId, args);
    }
    if (message.method === 'Network.loadingFinished' && requests.has(message.params.requestId)) {
      const args = requests.get(message.params.requestId); requests.delete(message.params.requestId);
      const job = cdp.call('Network.getResponseBody', { requestId: message.params.requestId }).then(result => {
        report.replies.push({ request: args, response: JSON.parse(result.base64Encoded ? Buffer.from(result.body, 'base64').toString('utf8') : result.body) });
      }).catch(error => report.errors.push(String(error))).finally(() => replyJobs.delete(job)); replyJobs.add(job);
    }
    if (message.method === 'Network.loadingFailed' && !message.params.canceled) report.requests.push(message.params.errorText);
  });
  await cdp.call('Runtime.enable'); await cdp.call('Page.enable'); await cdp.call('Network.enable');
  await cdp.call('Emulation.setDeviceMetricsOverride', { width: 1680, height: 1000, deviceScaleFactor: 1, mobile: false });
  if (report.session) await sessionJourney(boot);
  else {
  await open(boot); await echo('1.0.0', 1);
  if (report.exported) {
    await until(() => report.replies.length === 1, 'initial exported RPC observed');
    for (const kind of ['nan', 'negativeZero', 'undefined', 'function', 'cycle', 'sparse']) {
      await click('[data-python-web-invalid="' + kind + '"]');
      const failure = await until(() => cdp.evaluate(`(() => {try {const value=JSON.parse(document.querySelector('[data-python-web-echo-result]')?.textContent); return value.ok === false && value.error.message.startsWith(${JSON.stringify(kind + ': ')}) && value;} catch {return false;}})()`), 'Client JSON rejection: ' + kind);
      assert.match(failure.error.message, /rejected "args"/);
      assert.equal((await command('snapshot')).calls, 1);
      assert.equal(report.replies.length, 1);
    }
    report.steps.push({step: 'exported-client-rejects-six-invalid-json-values-before-host-call', passed: true});
    await click('[data-python-web-snapshot]');
    const snapshot = await until(() => cdp.evaluate(`(() => {try {const value=JSON.parse(document.querySelector('[data-python-web-echo-result]')?.textContent); return value.ok === true && value.value.args?.safe === true && value;} catch {return false;}})()`), 'detached JSON ignores hidden toJSON');
    assert.deepEqual(snapshot, {ok: true, value: {calls: 1, args: {safe: true}}});
    report.steps.push({step: 'exported-client-detaches-json-before-connection-serialization', passed: true});
    const timeOrigin = await cdp.evaluate('performance.timeOrigin');
    assert.equal(await count('style[data-dyn^="python-export-"]'), 1);
    await command('rebuild-client');
    await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'real HMR replaces exported Client');
    assert.equal(await cdp.evaluate('performance.timeOrigin'), timeOrigin);
    assert.equal(await count('style[data-dyn^="python-export-"]'), 1);
    await echo('1.0.0', 2);
    await command('restore-client');
    await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'real HMR restores package release bytes');
    assert.equal(await cdp.evaluate('performance.timeOrigin'), timeOrigin);
    assert.equal(await count('style[data-dyn^="python-export-"]'), 1);
    await echo('1.0.0', 3);
    report.steps.push({step: 'exported-client-real-hmr-disposes-old-styles-and-child-fiber-with-host-retained', passed: true});
  }
  await reloadPage();
  await until(() => cdp.evaluate('document.querySelector("[data-python-web-echo-result]")?.textContent === "ready"'), 'fresh Client after page reload');
  await echo('1.0.0', report.exported ? 4 : 2);
  report.steps.push({ step: 'page-refresh-restores-client-with-host-retained', passed: true });
  const unloaded = await command('unload');
  assert.equal(unloaded.calls, null); assert.equal(unloaded.descriptor, false); assert.equal(unloaded.seen, true);
  assert.equal(unloaded.graph.entries.some(row => row.id === packageName), false);
  // The pinned HMR deliberately keeps the initial boot graph until page reload.
  assert.equal(await count('[data-python-web-echo]'), 1);
  await click('[data-python-web-echo-call]');
  const rejected = await until(() => cdp.evaluate(`(() => {try {const value=JSON.parse(document.querySelector('[data-python-web-echo-result]')?.textContent); return value.ok === false && value;} catch {return false;}})()`), 'retained Client rejected after Host withdrawal');
  assert.match(JSON.stringify(rejected), /strict definition was withdrawn/);
  assert.equal((await command('snapshot')).calls, null);
  report.steps.push({ step: 'host-unload-withdraws-strict-remote-retained-client-call-rejected', passed: true });
  await reloadPage();
  await until(async () => !await count('[data-python-web-echo]') && await count('[class*="frame"]'), 'page reload reads graph without unloaded Client');
  report.steps.push({ step: 'page-refresh-removes-unloaded-client-from-original-boot-graph', passed: true });
  await transition('restart', '1.0.0');
  await transition('upgrade', '2.0.0');
  await transition('rollback', '1.0.0');
  await transition('remove', undefined, false);
  }
  await Promise.all([...replyJobs]);
  assert.equal(report.replies.length, report.session ? 15 : report.exported ? 9 : 6);
  for (const reply of report.replies) {
    assert.deepEqual(reply.request.payload, {args: report.session ? {agentId: reply.request.payload.args.agentId, method: 'echo', args: {text: '中文 portable'}} : report.exported ? reply.request.payload.args.method === 'snapshot' ? {method: 'snapshot', args: {safe: true}} : {method: 'echo', args: {text: '中文 portable'}} : {text: '中文 portable'}});
    if (report.session) assert.ok(['python-session-a', 'python-session-b', 'python-session-shared'].includes(reply.request.payload.args.agentId));
    assert.equal(reply.request.method, rpcEndpoint);
  }
  assert.equal(report.replies.filter(reply => reply.response.result.ok).length, report.session ? 13 : report.exported ? 8 : 5);
  assert.equal(report.replies.filter(reply => !reply.response.result.ok).length, report.session ? 2 : 1);
  assert.deepEqual(report.errors, []); assert.deepEqual(report.consoleErrors, []); assert.deepEqual(report.requests, []);
  assert.ok(report.sockets.includes('/api/remote.mux'));
  for (const [path, digest] of Object.entries(report.inputSha256)) assert.equal(createHash('sha256').update(await readFile(join(root, path))).digest('hex'), digest);
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = String(error.stack ?? error);
  if (cdp) { try { report.pageText = await cdp.evaluate('document.body.innerText'); } catch {} }
} finally {
  if (browser?.exitCode === null) { try { await cdp?.call('Browser.close'); await until(() => browser.exitCode !== null, 'browser closed'); } catch { browser.kill(); } }
  if (host?.exitCode === null) { try { await command('shutdown'); await until(() => host.exitCode !== null, 'Host closed'); } catch { host.kill(); } }
  cdp?.socket.close();
  report.hostErrors = hostErrors.replace(/token=[^\s]+/g, 'token=[redacted]'); report.hostExitCode = host?.exitCode;
  if (report.passed && (report.hostErrors || report.hostExitCode !== 0)) { report.passed = false; report.failure = 'Host teardown failed'; }
  assert.equal(resolve(dirname(privateBrowser)), resolve(tmpdir())); assert.ok(basename(privateBrowser).startsWith('dsh-web-package-cdp-'));
  await rm(privateBrowser, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  await writeFile(output, JSON.stringify(report, null, 2) + '\n', 'utf8');
}
console.log(JSON.stringify({ passed: report.passed, steps: report.steps.length, output, failure: report.failure }));
if (!report.passed) process.exitCode = 1;
