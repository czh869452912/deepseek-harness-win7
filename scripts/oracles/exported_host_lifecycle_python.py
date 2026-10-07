import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.cordis.fiber import FiberState
from dsh.extensions.packaged_host import host_handler_service, python_host_source


sys.path.insert(1, str(Path(__file__).resolve().parent))
from exported_host_lifecycle import observe_lifecycle


async def main(directory):
    rows = await observe_lifecycle(directory)
    imports = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            relative = selected.relative_to(ROOT).as_posix()
            imports[relative] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(ROOT), executable=sys.executable, python=sys.version, rows=rows,
                       imports=imports, fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(rows=len(rows), imports=len(imports))))


with tempfile.TemporaryDirectory(prefix='sdk-lifecycle-', dir=str(options.output.parent)) as directory:
    asyncio.run(main(Path(directory)))
