import hashlib
import json
import os
from pathlib import Path
import sys


selected_root = Path(os.environ['DSH_SDK_NATIVE_ROOT']).resolve()
sys.path.insert(0, str(selected_root))
from apps.cli.main import main


try:
    main()
finally:
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.') or name == 'apps' or name.startswith('apps.')):
            path = Path(filename).resolve()
            modules[path.relative_to(selected_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with Path(os.environ['DSH_SDK_RUNTIME_OUTPUT']).open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules), stream, indent=2)
        stream.write('\n')
