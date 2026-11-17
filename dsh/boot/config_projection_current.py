"""Private pure Config-graph projector carried from the fixed upstream revision.

This transport does not inspect Loader entries or serialize Python Schema nodes.
It uses the already shipped Win7 JavaScript engine, never a machine Node install.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dsh.javascript.runtime import (JavaScriptRuntimeError, encode,
                                    verify_resources, worker_environment)

RESOURCE_ROOT = Path(__file__).with_name('config-projection')
MANIFEST_SHA256 = '029ff3cb5ffbed032261dc1e83d60df070a4a15d71ca63a7c2d6ad362aed3b0f'


def projection_bootstrap():
    manifest_path = RESOURCE_ROOT / 'manifest.json'
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != MANIFEST_SHA256:
        raise JavaScriptRuntimeError('Config projection manifest bytes differ')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name:
            raise JavaScriptRuntimeError('Config projection resource path differs')
        if hashlib.sha256((RESOURCE_ROOT / name).read_bytes()).hexdigest() != expected:
            raise JavaScriptRuntimeError('Config projection resource bytes differ: ' + name)
    return (RESOURCE_ROOT / 'projector.js').read_text(encoding='utf-8') + '\n' + (
        RESOURCE_ROOT / 'driver.js').read_text(encoding='utf-8')


def project_config_graphs(graphs, async_projection=False):
    """Project encoded graphs; each row preserves shared identity across its roots.

    Graphs are trusted plugin structure represented by the private tagged transport,
    not plugin configuration values. Builder callbacks are represented by fixed
    graph references here; the live Python builder bridge is a separate layer.
    """
    if type(graphs) is not list:
        raise TypeError('Config projection graphs must be a list')
    request = dict(body='return null', name='cordis-config-projection', timeoutMs=5000,
                   graphs=graphs, asyncProjection=async_projection, bootstrap=projection_bootstrap())
    # Reject unencoded NaN/Infinity rather than silently changing graph semantics.
    payload = json.dumps(request, ensure_ascii=True, allow_nan=False).encode('utf-8') + b'\n'
    completed = subprocess.run([str(verify_resources())], input=payload + encode(dict(type='go')),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=worker_environment(), timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        frames = [json.loads(line.decode('utf-8')) for line in completed.stdout.splitlines()]
    except (UnicodeError, ValueError) as error:
        raise JavaScriptRuntimeError('Config projector returned invalid protocol data') from error
    if (completed.returncode != 0 or len(frames) != 2 or frames[0] != dict(type='ready')
            or frames[1].get('type') != 'terminal' or type(frames[1].get('result')) is not list
            or len(frames[1]['result']) != len(graphs)):
        raise JavaScriptRuntimeError('Config projector failed: ' + completed.stderr.decode('utf-8', errors='replace')
                                     + '\n' + completed.stdout.decode('utf-8', errors='replace'))
    return frames[1]['result']
