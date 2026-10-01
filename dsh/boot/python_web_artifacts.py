"""Validate explicitly supplied prebuilt Web assets without executing package code."""
import ast
import hashlib
import json
import os

from dsh.boot.python_package import inside
from dsh.host.client_modules.registry import ABSENT, client_export_of, parse_dsh_client, validate_source_map


def export_target(manifest, key):
    exports = manifest.get('exports')
    value = exports.get(key) if isinstance(exports, dict) else None
    if isinstance(value, dict):
        value = value.get('default')
    if not isinstance(value, str) or not value.startswith('./'):
        raise ValueError('Python Web package must export a relative ' + key + ' artifact')
    return value[2:]


def validate_web_artifacts(directory, manifest):
    dsh = manifest['dsh']
    client = parse_dsh_client(manifest['name'], dsh.get('client', ABSENT))
    receipt = dsh.get('webArtifacts')
    if client is None:
        if receipt is not None:
            raise ValueError('webArtifacts requires a dsh.client declaration')
        return
    if client['platform'] != 'web':
        raise ValueError('Python plugin client platform must be web')
    target = client_export_of(manifest['name'], manifest.get('exports'))
    if not isinstance(target, str) or not target.startswith('./'):
        raise ValueError('Python Web package requires a relative ./client export')
    target = target[2:]
    if not target.endswith('.js'):
        raise ValueError('Client export must be prebuilt JavaScript')
    if not isinstance(receipt, dict) or set(receipt) != {'formatVersion', 'targetUpstream', 'files'}:
        raise ValueError('Python Web package requires an explicit webArtifacts build receipt')
    if type(receipt['formatVersion']) is not int or receipt['formatVersion'] != 1:
        raise ValueError('unsupported Web artifact receipt version')
    # This is the actual reference protocol target used by this Host. A hash
    # label is compatibility intent, not a claim of Win7/browser certification.
    with open(os.path.join(os.path.dirname(__file__), '..', 'extensions', 'inspect_catalog.json'), encoding='utf-8') as stream:
        current_target = json.load(stream)['target_upstream']
    if receipt['targetUpstream'] != current_target:
        raise ValueError('Web artifact target does not match the pinned Host protocol')
    files = receipt['files']
    if not isinstance(files, dict) or not files or target not in files:
        raise ValueError('Web artifact receipt must include the Client bundle')
    for relative, digest in files.items():
        path = inside(directory, relative)
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
            raise ValueError('Web artifact hash must be SHA-256')
        if not os.path.isfile(path):
            raise ValueError('Web artifact is missing: ' + relative)
        with open(path, 'rb') as stream:
            data = stream.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Web artifact differs from its build receipt: ' + relative)
        if relative == target and not data.strip():
            raise ValueError('Client bundle must not be empty')
        if relative.endswith('.py'):
            try:
                compile(data, path, 'exec', ast.PyCF_ONLY_AST, dont_inherit=True)
            except SyntaxError as error:
                raise ValueError('invalid Python syntax in Web artifact: ' + relative) from error
    if os.path.isfile(inside(directory, target + '.map')):
        if target + '.map' not in files:
            raise ValueError('Client source map must be included in the Web build receipt')
        with open(inside(directory, target + '.map'), 'rb') as stream:
            validate_source_map(target, stream.read())
    if './typert' in manifest.get('exports', {}):
        remote = export_target(manifest, './typert')
        if remote not in files or not remote.endswith(('.py', '.js')):
            raise ValueError('Host Typert artifact must be supplied in the Web build receipt')
    # Arbitrary imports cannot be proved by scanning JavaScript. Authors list
    # every relative runtime asset here and real browser validation proves it.
    return receipt
