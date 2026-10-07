import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
selected_root = arguments.root.resolve()
work = arguments.output.parent
sys.path.insert(0, str(selected_root))
from dsh.fs.tool_read_render import build_window, format_read_output, lang_from_path, read_meta_from_meta


async def chunks(values):
    for value in values:
        yield value


async def main():
    fixtures = json.loads((Path(__file__).resolve().parent / 'read-window-fixtures-v2.json').read_text(encoding='utf-8'))
    rows = []
    for fixture in fixtures['windows']:
        request = dict(offset=1, limit=2000, maxLineLength=2000, maxBytes=51200)
        request.update(fixture.get('request', {}))
        for delivery in ('sync', 'async'):
            values = fixture['chunks'] if delivery == 'sync' else chunks(fixture['chunks'])
            row = dict(name='window/%s/%s' % (fixture['name'], delivery))
            try:
                outcome = await build_window(values, request, 'fixture.txt')
                row['value'] = dict(outcome=outcome, rendered=format_read_output('fixture.txt', dict(offset=request['offset'], **outcome)))
            except Exception as error:
                row['error'] = dict(message=str(error), code=getattr(error, 'code', None))
            rows.append(row)
    rows.extend(dict(name='language/%s' % index, value=lang_from_path(path)) for index, path in enumerate(fixtures['paths']))
    rows.extend(dict(name='metadata/%s' % index, value=read_meta_from_meta(meta)) for index, meta in enumerate(fixtures['metadata']))
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            relative = path.relative_to(selected_root).as_posix()
            modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


asyncio.run(main())
