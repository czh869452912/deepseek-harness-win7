import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
NAMES = ('effort-off', 'effort-low', 'effort-high', 'effort-max', 'title', 'disabled-effort', 'tool-history', 'cache', 'detail-cache', 'inexact-total', 'utf8-bytewise', 'empty', 'truncated', 'malformed', 'unterminated', 'tool-fragments', 'model-default', 'model-unlisted', 'model-disabled', 'model-custom', 'http-success', 'http-truncated', 'http-extension', 'http-collision', 'http-accept-failed', 'http-rejected-extension', 'http-rate-limit', 'http-quota', 'http-context', 'http-auth', 'http-idle', 'http-cancel', 'http-image-file', 'http-image-inline', 'http-image-partial-fallback', 'http-image-tool-result', 'http-image-reject-system', 'http-image-reject-offloaded-system', 'http-image-count-budget', 'files-upload', 'files-upload-no-expiry', 'files-expiry-rejected', 'files-retrieve', 'files-invalid-bytes', 'files-page', 'files-invalid-page', 'files-delete', 'files-delete-mismatch', 'files-quota', 'files-auth', 'config-defaults', 'config-explicit', 'config-low-image', 'config-contradiction', 'config-duplicate-model', 'config-text-image-limits', 'config-duplicate-modality', 'config-file-byte-budget', 'config-inline-byte-budget', 'config-count-budget', 'config-expiry', 'config-refresh', 'config-quota-batch', 'config-timer', 'config-retry-backoff', 'config-retry-unknown', 'config-retry-duplicate', 'config-environment', 'settings-last-good-duplicate', 'settings-last-good-schema', 'settings-last-good-retry', 'http-retry-server-recovery', 'http-retry-auth-refusal', 'http-retry-exhausted', 'http-retry-retry-after-too-long', 'http-retry-always-auth-recovery')


def error_row(error, code=None):
    result = dict(code=code or getattr(error, 'code', type(error).__name__),
        name=getattr(error, 'name', type(error).__name__), message=getattr(error, 'message', str(error)))
    if getattr(error, 'failure', None) is not None:
        result['failure'] = error.failure
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    sys.path.append(str(SCRIPT_ROOT / 'scripts/oracles'))
    from dsh.llm.deepseek_wire import serialize_request, translate, parse_sse, map_usage
    from dsh.llm.deepseek_config import resolve_options
    from dsh.llm.llm_deepseek import DeepSeekAdapter
    from deepseek_capture_http_python import observe
    from deepseek_capture_files_python import observe_files
    from deepseek_capture_settings_python import observe_settings
    fixtures = json.loads((SCRIPT_ROOT / 'scripts/oracles/deepseek-fixtures.json').read_text(encoding='utf-8'))
    assert tuple(fixture['id'] for fixture in fixtures) == NAMES
    source = json.loads(options.source.read_text(encoding='utf-8'))
    assert [row['id'] for row in source['rows']] == [fixture['id'] for fixture in fixtures]
    rows = []
    for fixture, source_row in zip(fixtures, source['rows']):
        row = dict(id=fixture['id'])
        kind = fixture['kind']
        if kind == 'config':
            try:
                row['value'] = resolve_options(fixture['config'], {name: dict(value=value) for name, value in fixture.get('environment', {}).items()})
            except (ValueError, TypeError) as error:
                row['error'] = error_row(error, 'CONFIG_REJECTED')
            rows.append(row)
            continue
        try:
            if kind == 'settings':
                row['value'] = asyncio.run(observe_settings(fixture))
            elif kind == 'files':
                row['value'] = observe_files(fixture)
            elif kind == 'http':
                row['value'] = asyncio.run(observe(fixture))
            elif kind == 'serialize':
                row['value'] = serialize_request(fixture['options'], fixture.get('defaults'))
            elif kind == 'usage':
                row['value'] = map_usage(fixture['usage'])
            elif kind == 'stream':
                row['value'] = []
                data, stride = fixture['sse'].encode('utf-8'), fixture['stride']
                for chunk in translate(parse_sse(data[index:index + stride] for index in range(0, len(data), stride))):
                    row['value'].append(chunk)
            elif kind == 'model':
                row['value'] = DeepSeekAdapter.model_info(resolve_options(fixture['config'], {}), 'deepseek-official', fixture['model'])
            else:
                raise ValueError('Unknown fixture kind: ' + kind)
        except Exception as error:
            row['error'] = error_row(error)
        rows.append(row)
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows,
            scope='76 selected captures retain all observed values, complete selected errors and retry data. HTTP/Files independently bind real loopback origins and retain coherent listener/configured endpoint facts. Retry orchestration remains a probe, not full canonical AgentLoop. No arbitrary graph/cancellation/paid/Win7 claim.'), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
