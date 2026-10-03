import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(not NODE, reason='development observer helper requires Node')


def observe(spec):
    source = r'''
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
const {credentialFreeEnvironment, deferProviderOnboarding} = await import(process.argv[1]);
const spec = JSON.parse(process.argv[2]);
const inherited = {PATH: 'developer tools', DEEPSEEK_API_KEY: 'not-a-real-key',
  openai_api_key: 'not-a-real-key', ANTHROPIC_ACCESS_TOKEN: 'not-a-real-token',
  DSH_HOME: 'real-user-home', PYTHONPATH: 'outside', SYSTEMROOT: 'Windows'};
const environment = credentialFreeEnvironment(inherited);
assert.equal(inherited.DEEPSEEK_API_KEY, 'not-a-real-key');
assert.deepEqual(environment, {PATH: 'developer tools', SYSTEMROOT: 'Windows'});
const actions = [], waits = [];
let visible = !spec.absent, inert = spec.interactive ? false : true;
const button = {
  textContent: spec.locale === 'zh' ? '稍后配置' : 'Configure later',
  disabled: Boolean(spec.disabled),
  getBoundingClientRect: () => ({x: 10, y: 20, width: 100, height: 40}),
  contains: element => element === button,
};
const dialog = {querySelectorAll: () => [button]};
const document = {
  querySelector: selector => visible && selector.includes(spec.locale === 'zh'
    ? '添加一个 API Key 开始使用' : 'Add an API key to get started') ? dialog : null,
  getElementById: () => ({inert}),
  elementFromPoint: () => spec.obstructed ? null : button,
};
const connection = {
  evaluate: expression => Promise.resolve(runInNewContext(expression, {document})),
  call: async (method, value) => {
    assert.equal(method, 'Input.dispatchMouseEvent');
    actions.push(value);
    if (value.type === 'mouseReleased') {visible = false; inert = Boolean(spec.stuck);}
  },
};
const waitFor = async (read, label) => {
  waits.push(label);
  for (let attempt = 0; attempt < 3; attempt++) {
    const value = await read();
    if (value) return value;
  }
  throw new Error('Timed out: ' + label);
};
let failure = null;
let deferred = null;
try {deferred = await deferProviderOnboarding(connection, waitFor, spec.required ?? true);} catch (error) {failure = error.message;}
console.log(JSON.stringify({actions, waits, failure, environment, deferred}));
'''
    result = subprocess.run([NODE, '--input-type=module', '-e', source.strip().replace('\n', ' '),
                             (ROOT / 'scripts/browser_onboarding.mjs').as_uri(), json.dumps(spec)],
                            capture_output=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('locale', ['en', 'zh'])
def test_defer_uses_real_mouse_controls_and_waits_for_application_interactivity(locale):
    report = observe({'locale': locale})
    assert report['failure'] is None
    assert report['actions'] == [
        {'type': 'mousePressed', 'x': 60, 'y': 40, 'button': 'left', 'clickCount': 1},
        {'type': 'mouseReleased', 'x': 60, 'y': 40, 'button': 'left', 'clickCount': 1},
    ]
    assert report['waits'] == ['original provider onboarding defer button',
                               'provider onboarding dismissed and application interactive']


@pytest.mark.parametrize('condition', ['absent', 'disabled', 'obstructed'])
def test_missing_or_inaccessible_onboarding_is_not_silently_accepted(condition):
    report = observe({'locale': 'en', condition: True})
    assert report['actions'] == []
    assert report['failure'] == 'Timed out: original provider onboarding defer button'


def test_dismissal_does_not_pass_when_application_remains_inert():
    report = observe({'locale': 'en', 'stuck': True})
    assert len(report['actions']) == 2
    assert report['failure'] == 'Timed out: provider onboarding dismissed and application interactive'


def test_repeat_navigation_allows_absent_dialog_only_when_application_is_interactive():
    report = observe({'absent': True, 'interactive': True, 'required': False})
    assert report['failure'] is None
    assert report['deferred'] is False
    assert report['actions'] == []
    blocked = observe({'absent': True, 'required': False})
    assert blocked['failure'] == 'Timed out: original provider onboarding defer button'


def test_first_navigation_requires_dialog_even_when_application_is_interactive():
    report = observe({'absent': True, 'interactive': True})
    assert report['failure'] == 'Timed out: original provider onboarding defer button'


@pytest.mark.parametrize('committed', [True, False])
def test_reload_waits_for_new_document_not_the_previous_application_shell(committed):
    source = r'''
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
const {reloadOriginalPage} = await import(process.argv[1]);
const committed = JSON.parse(process.argv[2]);
const performance = {timeOrigin: 10}, actions = [];
const connection = {
  evaluate: expression => Promise.resolve(runInNewContext(expression, {performance})),
  call: async (method, parameters) => {actions.push({method, parameters});},
};
let polls = 0, failure = null;
const waitFor = async (read, label) => {
  assert.equal(label, 'new document after original page reload');
  assert.equal(await read(), false);
  for (polls = 1; polls < 4; polls++) {
    if (committed && polls === 2) performance.timeOrigin = 20;
    if (await read()) return true;
  }
  throw new Error('Timed out: ' + label);
};
try {await reloadOriginalPage(connection, waitFor, {ignoreCache: true});} catch (error) {failure = error.message;}
console.log(JSON.stringify({actions, polls, failure}));
'''
    result = subprocess.run([NODE, '--input-type=module', '-e', source.strip().replace('\n', ' '),
                             (ROOT / 'scripts/browser_onboarding.mjs').as_uri(), json.dumps(committed)],
                            capture_output=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['actions'] == [{'method': 'Page.reload', 'parameters': {'ignoreCache': True}}]
    assert report['failure'] == (None if committed else 'Timed out: new document after original page reload')
    assert report['polls'] >= 2


@pytest.mark.parametrize('launcher_exited', [True, False])
@pytest.mark.parametrize('disconnected', [True, False])
def test_browser_close_uses_live_protocol_even_after_launcher_exit_and_requires_disconnect(launcher_exited, disconnected):
    source = r'''
const {closeOriginalBrowser} = await import(process.argv[1]);
const spec = JSON.parse(process.argv[2]);
const actions = [], waits = [];
const browser = {exitCode: spec.launcherExited ? 0 : null, signalCode: null,
  kill: () => { actions.push('kill'); browser.signalCode = 'SIGTERM'; }};
const connection = {socket: {readyState: 1},
  call: async method => {actions.push(method);}};
const waitFor = async (read, label) => {
  waits.push({label, initially: await read()});
  if (label.includes('protocol')) {
    if (spec.disconnected) connection.socket.readyState = 3;
  } else browser.exitCode = 0;
  if (!await read()) throw new Error('Timed out: ' + label);
};
let failure = null;
try {await closeOriginalBrowser(connection, browser, waitFor);} catch (error) {failure = error.message;}
console.log(JSON.stringify({actions, waits, failure}));
'''
    result = subprocess.run([NODE, '--input-type=module', '-e', source.strip().replace('\n', ' '),
        (ROOT / 'scripts/browser_onboarding.mjs').as_uri(), json.dumps({'launcherExited': launcher_exited, 'disconnected': disconnected})],
        capture_output=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['actions'] == ['Browser.close']
    assert report['waits'][0] == {'label': 'original browser protocol disconnected', 'initially': False}
    assert report['failure'] == (None if disconnected else 'Timed out: original browser protocol disconnected')
