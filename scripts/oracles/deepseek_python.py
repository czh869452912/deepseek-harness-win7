"""Same fixture inputs through the product implementation, without HTTP mocks."""
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.llm.deepseek_wire import serialize_request, translate, parse_sse, map_usage
from dsh.llm.deepseek_config import resolve_options
from dsh.llm.llm_deepseek import DeepSeekAdapter
from deepseek_http_python import observe
from deepseek_files_python import observe_files
from deepseek_settings_python import observe_settings


def main():
    rows = []
    for fixture in json.loads((ROOT / 'scripts/oracles/deepseek-fixtures.json').read_text(encoding='utf-8')):
        row = {'id': fixture['id']}
        if fixture['kind'] == 'config':
            try:
                row['value'] = resolve_options(fixture['config'], {key: {'value': value} for key, value in fixture.get('environment', {}).items()})
            except (ValueError, TypeError):
                row['error'] = {'code': 'CONFIG_REJECTED'}
            rows.append(row)
            continue
        try:
            kind = fixture['kind']
            if kind == 'settings':
                row['value'] = asyncio.run(observe_settings(fixture))
            if kind == 'files':
                row['value'] = observe_files(fixture)
            if kind == 'http':
                row['value'] = asyncio.run(observe(fixture))
            if kind == 'serialize':
                row['value'] = serialize_request(fixture['options'], fixture.get('defaults'))
            elif kind == 'usage':
                row['value'] = map_usage(fixture['usage'])
            elif kind == 'stream':
                row['value'] = []
                data, stride = fixture['sse'].encode('utf-8'), fixture['stride']
                for chunk in translate(parse_sse(data[i:i + stride] for i in range(0, len(data), stride))):
                    row['value'].append(chunk)
            elif kind == 'model':
                row['value'] = DeepSeekAdapter.model_info(resolve_options(fixture['config'], {}), 'deepseek-official', fixture['model'])
        except Exception as error:
            row['error'] = {'code': getattr(error, 'code', type(error).__name__)}
        rows.append(row)
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
