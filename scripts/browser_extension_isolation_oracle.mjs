import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {createServer} from 'node:http';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {isolatedBrowserArguments} from './browser_onboarding.mjs';

const browserPath = process.argv[2];
if (!browserPath || !process.argv[3]) throw new Error('Use <Chromium> <report.json>');
const output = resolve(process.argv[3]);
const fixture = await mkdtemp(join(tmpdir(), 'dsh-extension-fixture-'));
await writeFile(join(fixture, 'manifest.json'), JSON.stringify({manifest_version:3, name:'DSH controlled extension fixture', version:'1.0',
  content_scripts:[{matches:['http://127.0.0.1/*'], js:['content.js'], run_at:'document_end'}]}), 'utf8');
await writeFile(join(fixture, 'content.js'), 'document.documentElement.dataset.dshExtensionFixture = "loaded"; console.error("DSH_CONTROLLED_EXTENSION_ERROR"); throw new Error("DSH_CONTROLLED_EXTENSION_EXCEPTION");', 'utf8');
const server = createServer((request, response) => {response.setHeader('Content-Type', 'text/html'); response.end('<!doctype html><html><body>Controlled browser isolation fixture</body></html>');});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const url = `http://127.0.0.1:${server.address().port}/`;
const delay = milliseconds => new Promise(done => setTimeout(done, milliseconds));
async function until(read, label, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {const value = await read(); if (value) return value; await delay(50);}
  throw new Error('Timed out: ' + label);
}
async function observe(disabled) {
  const profile = await mkdtemp(join(tmpdir(), 'dsh-extension-isolation-'));
  const args = isolatedBrowserArguments(profile).filter(argument => disabled || argument !== '--disable-extensions');
  args.splice(args.length - 1, 0, '--enable-automation', `--load-extension=${fixture}`);
  const browser = spawn(browserPath, args, {windowsHide:true});
  const report = {disabled, profile, args, contexts:[], console:[], exceptions:[]};
  let socket;
  const pending = new Map();
  let next = 1;
  async function call(method, params = {}) {
    const id = next++;
    return await new Promise((yes, no) => {
      const timer = setTimeout(() => {pending.delete(id); no(new Error('CDP timeout: ' + method));}, 15000);
      pending.set(id, {yes, no, timer});
      socket.send(JSON.stringify({id, method, params}));
    });
  }
  async function evaluate(expression) {
    const result = await call('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  }
  try {
    const port = await until(async () => {try {return (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0];} catch {return false;}}, 'private CDP port');
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
    await new Promise((yes, no) => {socket.addEventListener('open', yes, {once:true}); socket.addEventListener('error', no, {once:true});});
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const request = pending.get(message.id);
        if (!request) return;
        pending.delete(message.id); clearTimeout(request.timer);
        message.error ? request.no(new Error(JSON.stringify(message.error))) : request.yes(message.result);
      } else if (message.method === 'Runtime.executionContextCreated') report.contexts.push(message.params.context);
      else if (message.method === 'Runtime.consoleAPICalled') report.console.push(message.params);
      else if (message.method === 'Runtime.exceptionThrown') report.exceptions.push(message.params);
    });
    await call('Runtime.enable'); await call('Page.enable');
    report.commandLine = await call('Browser.getBrowserCommandLine');
    report.version = await call('Browser.getVersion');
    await call('Page.navigate', {url:'edge://extensions/'});
    await until(() => evaluate('typeof chrome.developerPrivate?.getExtensionsInfo === "function"'), 'extension inventory API');
    report.inventory = await evaluate('new Promise(resolve => chrome.developerPrivate.getExtensionsInfo({includeDisabled:true, includeTerminated:true}, resolve))');
    await call('Page.navigate', {url});
    await until(() => evaluate('document.readyState === "complete" && location.href === ' + JSON.stringify(url)), 'local complete page');
    if (!disabled) await until(() => evaluate('document.documentElement.dataset.dshExtensionFixture === "loaded"'), 'fixture injection');
    report.marker = await evaluate('document.documentElement.dataset.dshExtensionFixture ?? null');
    await evaluate('console.error("DSH_CONTROLLED_APP_ERROR"); setTimeout(() => {throw new Error("DSH_CONTROLLED_APP_EXCEPTION");}, 0); true');
    await until(() => report.exceptions.some(event => event.exceptionDetails.exception?.description?.includes('DSH_CONTROLLED_APP_EXCEPTION')), 'app exception still observed');
    await call('Browser.close');
    await until(() => socket.readyState === WebSocket.CLOSED, 'browser disconnected');
    return report;
  } finally {
    if (socket?.readyState === WebSocket.OPEN) socket.close();
    if (browser.exitCode === null && browser.signalCode === null) browser.kill();
  }
}
const result = {kind:'controlled-browser-extension-isolation', fixture, url, observations:[]};
try {
  for (const disabled of [false, true]) result.observations.push(await observe(disabled));
  assert.equal(result.observations[0].marker, 'loaded');
  assert.equal(result.observations[1].marker, null);
  assert(result.observations[0].exceptions.some(event => event.exceptionDetails.exception?.description?.includes('DSH_CONTROLLED_EXTENSION_EXCEPTION')));
  assert(!result.observations[1].exceptions.some(event => event.exceptionDetails.exception?.description?.includes('DSH_CONTROLLED_EXTENSION_EXCEPTION')));
  for (const observation of result.observations) {
    assert(observation.commandLine.arguments.includes('--user-data-dir=' + observation.profile));
    assert.equal(observation.commandLine.arguments.includes('--disable-extensions'), observation.disabled);
    const fixtureExtensions = observation.inventory.filter(extension => extension.name === 'DSH controlled extension fixture');
    assert.equal(fixtureExtensions.length, observation.disabled ? 0 : 1);
    assert.equal(observation.console.filter(event => event.type === 'error').length, observation.disabled ? 1 : 2);
    assert.equal(observation.exceptions.length, observation.disabled ? 1 : 2);
    assert(observation.console.some(event => event.args.some(argument => argument.value === 'DSH_CONTROLLED_APP_ERROR')));
    assert(observation.exceptions.some(event => event.exceptionDetails.exception?.description?.includes('DSH_CONTROLLED_APP_EXCEPTION')));
    if (observation.disabled) assert(!observation.contexts.some(context => context.origin.startsWith('chrome-extension://')));
    else assert(observation.contexts.some(context => context.origin === 'chrome-extension://' + fixtureExtensions[0].id));
  }
  result.passed = true;
} catch (error) {result.passed = false; result.failure = error.stack; process.exitCode = 1;}
finally {await writeFile(output, JSON.stringify(result, null, 2) + '\n', 'utf8'); server.close();}
console.log(JSON.stringify({passed:result.passed, failure:result.failure, observations:result.observations.map(item => ({disabled:item.disabled, marker:item.marker, extensions:item.inventory.map(extension => ({id:extension.id, name:extension.name, state:extension.state}))}))}));
