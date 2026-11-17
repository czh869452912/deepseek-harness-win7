"""Pinned market format-1 validator/search in the shipped Win7 JavaScript worker.

This private carrier accepts JSON values, not untrusted executable source. It
does not fetch indexes, validate Gateway queries, or claim Node JSON diagnostics.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dsh.javascript.runtime import (JavaScriptRuntimeError, encode,
                                    verify_resources, worker_environment)

RESOURCE_ROOT = Path(__file__).with_name('market-index')
MANIFEST_SHA256 = '28850de64d283184ee7b51fbe5bfa44c706ae7a6d8ce352fcaafef5d41a0e1e7'


class MarketIndexError(ValueError):
    def __init__(self, path, reason):
        self.path, self.reason = path, reason
        super().__init__(path + ' ' + reason)


def market_bootstrap():
    path = RESOURCE_ROOT / 'manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('Market index manifest bytes differ')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('format') != 'dsh-market-index@1' or manifest.get('target_upstream') != '38a6a5c965aa99ab525161efb7cc5cf1fe62fced':
        raise JavaScriptRuntimeError('Market index Source pin differs')
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name:
            raise JavaScriptRuntimeError('Market index resource path differs')
        if hashlib.sha256((RESOURCE_ROOT / name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('Market index resource bytes differ: ' + name)
    # The shared core-js artifact replaces an incompatible existing constructor.
    # This worker has no native URL; the sentinel selects that same full parser.
    return 'globalThis.URL=function(){this.hostname="";};\n' + '\n'.join(
        (RESOURCE_ROOT / name).read_text(encoding='utf-8') for name in ('url.js', 'market.js', 'driver.js'))


def observe_market_operations(operations):
    if type(operations) is not list:
        raise TypeError('Market operations must be a list')
    request = dict(body='return null', name='market-index', timeoutMs=10000,
                   operations=operations, bootstrap=market_bootstrap())
    completed = subprocess.run([str(verify_resources())], input=encode(request) + encode(dict(type='go')),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(), timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        frames = [json.loads(line.decode('utf-8')) for line in completed.stdout.splitlines()]
    except (UnicodeError, ValueError) as error:
        raise JavaScriptRuntimeError('Market worker returned invalid protocol data') from error
    if (completed.returncode != 0 or len(frames) != 2 or frames[0] != dict(type='ready')
            or frames[1].get('type') != 'terminal' or type(frames[1].get('result')) is not list
            or len(frames[1]['result']) != len(operations)):
        # Worker errors may contain the entire bootstrap. Keep diagnostics bounded.
        raise JavaScriptRuntimeError('Market worker failed (exit ' + str(completed.returncode) + '): '
            + completed.stderr.decode('utf-8', errors='replace')[-2000:])
    return frames[1]['result']


def parse_market_index(value, url):
    row = observe_market_operations([dict(kind='parse', value=value, url=url)])[0]
    if row['ok']:
        return row['index']
    error = row['error']
    if error['name'] == 'MarketIndexError':
        raise MarketIndexError(error['path'], error['reason'])
    raise ValueError(error['message'])
