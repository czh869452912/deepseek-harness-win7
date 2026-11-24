'use strict';

const assert = require('node:assert/strict');
const children = require('node:child_process');
const path = require('node:path');
const {performance} = require('node:perf_hooks');

const root = process.cwd();
const python = process.argv[2];
const legacy = process.argv[3] === 'legacy';
const spawn = children.spawn;
children.spawn = (binary, args, options) => {
  assert.equal(args[1], 'dsh.host.desktop.process');
  return spawn(binary, ['-B', path.join(__dirname, 'desktop_pipe_host.py'), ...(legacy ? ['legacy'] : [])], options);
};
const {DesktopHostProcess} = require(path.join(root, 'apps', 'desktop', 'host-process.cjs'));
children.spawn = spawn;

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(condition) {
  const deadline = performance.now() + 3000;
  while (!await condition()) {
    assert.ok(performance.now() < deadline, 'expected pipe state did not arrive');
    await sleep(5);
  }
}

async function run() {
  const host = new DesktopHostProcess({python, root, profile: __dirname, home: __dirname});
  const fetch = (name, options) => host.fetch({url: 'dsh-app://app/' + name, ...options});
  const read = async response => {
    const chunks = [];
    for await (const chunk of response.body) chunks.push(chunk);
    return Buffer.concat(chunks);
  };
  try {
    await host.start();
    assert.equal(host.responseCredit, !legacy);
    const slow = await fetch('large');
    await until(() => slow.body.writableLength >= 65536);
    if (legacy) {
      assert.ok(host.child.stdout.isPaused());
      assert.equal((await read(slow)).length, 4 * 1024 * 1024);
      assert.equal((await read(await fetch('small'))).toString(), 'ok');
      return;
    }

    assert.ok(!host.child.stdout.isPaused());
    assert.equal((await read(await fetch('small'))).toString(), 'ok');
    assert.ok(slow.body.readableLength + slow.body.writableLength <= 6 * 65536);
    assert.deepEqual(await read(slow), Buffer.alloc(4 * 1024 * 1024, 'x'));

    for (const cancel of ['destroy', 'abort']) {
      const signal = new AbortController();
      const response = await fetch('large', {signal: signal.signal});
      await until(() => response.body.writableLength >= 65536);
      if (cancel === 'destroy') response.body.destroy();
      else signal.abort();
      await until(async () => Number((await read(await fetch('closed'))).toString()) ===
        (cancel === 'destroy' ? 2 : 3));
    }
    assert.equal((await read(await fetch('small'))).toString(), 'ok');
  } finally {
    await host.stop();
  }
}

run().catch(error => {console.error(error); process.exitCode = 1;});
