"""Compile Client code in Function-body context on the shipped Win7 worker.

The pinned grammar disables productions absent from the fixed Node gate;
it does not certify every Node/V8 syntax edge. No model code is executed.
"""
import hashlib
import json
from pathlib import Path
import os
import re
import subprocess

from dsh.javascript.runtime import (JavaScriptParseError, JavaScriptRuntimeError,
                                    encode, verify_resources, worker_environment)

RESOURCE_ROOT = Path(__file__).with_name('client-syntax')
MANIFEST_SHA256 = '73c59f97bbdd80dfc7257c59ffc4fff73caf9ec5a2d306dcd7edeb0348664ee0'


def client_syntax_bootstrap():
    manifest_path = RESOURCE_ROOT / 'manifest.json'
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('Client syntax manifest bytes differ')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name:
            raise JavaScriptRuntimeError('Client syntax resource path differs')
        if hashlib.sha256((RESOURCE_ROOT / name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('Client syntax resource bytes differ: ' + name)
    return (RESOURCE_ROOT / 'acorn.js').read_text(encoding='utf-8') + '\n' + (
        RESOURCE_ROOT / 'driver.js').read_text(encoding='utf-8')


def precheck_client_body(body):
    if type(body) is not str:
        raise TypeError('Client body must be a string')
    request = dict(body='return null', name='cordis-client-precheck-driver', timeoutMs=5000,
                   clientCode=body, bootstrap=client_syntax_bootstrap())
    completed = subprocess.run([str(verify_resources())], input=encode(request) + encode(dict(type='go')),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        frames = [json.loads(line.decode('utf-8')) for line in completed.stdout.splitlines()]
    except (UnicodeError, ValueError) as error:
        raise JavaScriptRuntimeError('Client parser returned invalid protocol data') from error
    if (completed.returncode != 0 or len(frames) != 2 or frames[0] != dict(type='ready')
            or frames[1].get('type') != 'terminal' or type(frames[1].get('result')) is not dict):
        raise JavaScriptRuntimeError('Client parser failed: ' + completed.stderr.decode('utf-8', errors='replace'))
    result = frames[1]['result']
    if result.get('ok') is True:
        return
    if result.get('ok') is not False or type(result.get('message')) is not str:
        raise JavaScriptRuntimeError('Client parser returned an invalid result')
    line, column = result.get('line'), result.get('column')
    context = ''
    lines = body.split('\n')
    if type(line) is int and 1 <= line <= len(lines) and type(column) is int and column >= 0:
        context = 'code.client:{}:{}\n{}\n{}^\n'.format(line, column + 1, lines[line - 1], ' ' * column)
    error = JavaScriptParseError(context + 'SyntaxError: ' + result['message'])
    error.offending_line = lines[line - 1] if type(line) is int and 1 <= line <= len(lines) else ''
    raise error


def client_parse_error_message(error):
    message = 'dynamic package `code.client` failed to parse:\n' + str(error) + '\n'
    if re.search(r'\bas\b', getattr(error, 'offending_line', '')):
        return message + ('The sandbox runs plain JavaScript, not TypeScript. Remove type annotations:\n'
                          "  ✗ { type: 'text' as const, text: x }\n"
                          "  ✓ { type: 'text', text: x }")
    return message + ('Note: it runs as the BODY of an async function (code.client line numbers refer to your body). '
                      'Check bracket balance — ending the returned plugin object with `});` closes a call that was never opened; '
                      'a plain `return { … }` ends with `}` (an optional `;`), never `)`.')
