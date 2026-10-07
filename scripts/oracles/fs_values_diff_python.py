import argparse
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
from dsh.fs.tool_diff import compute_hunk_diffs, diffs_from_meta


fixtures = json.loads((Path(__file__).resolve().parent / 'diff-fixtures-v1.json').read_text(encoding='utf-8'))
rows = [dict(name='diff/' + fixture['name'], value=compute_hunk_diffs(fixture['path'], fixture['before'], fixture['after'])) for fixture in fixtures['cases']]
rows.extend(dict(name='metadata/%s' % index, value=diffs_from_meta(meta)) for index, meta in enumerate(fixtures['metadata']))
modules = {}
for name, module in sorted(sys.modules.items()):
    filename = getattr(module, '__file__', None)
    if filename and (name == 'dsh' or name.startswith('dsh.')):
        path = Path(filename).resolve()
        relative = path.relative_to(selected_root).as_posix()
        modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules, fixtureSha256=hashlib.sha256((Path(__file__).resolve().parent / 'diff-fixtures-v1.json').read_bytes()).hexdigest(), rows=rows), stream, ensure_ascii=True, indent=2)
    stream.write('\n')
