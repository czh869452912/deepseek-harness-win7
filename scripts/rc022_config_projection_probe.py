"""Compare the fixed Source projector with its shipped Win7 engine carrier."""
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
_output = None


def prepare(output):
    global _output
    _output = output
    return []


async def observe():
    return await observe_mode()


async def observe_mode(async_projection=False):
    from dsh.boot.config_projection_current import project_config_graphs
    source = json.loads((_output / 'source.json').read_text(encoding='utf-8'))
    # Only encoded graph inputs cross this boundary; expected projections are not read.
    values = project_config_graphs([row['wire'] for row in source], async_projection=async_projection)
    return [dict(name=row['name'], wire=row['wire'], observation=value) for row, value in zip(source, values)]


if __name__ == '__main__':
    probe.native = observe
    resources = ROOT / 'dsh/boot/config-projection'
    probe.main('rc022_config_projection.mts', prepare=prepare,
        scope='Actual fixed Source Schemastery graphs projected by Source and by unchanged bundled projector/Ajv/regexpp on shipped Win7 QuickJS. Includes omission/default/null, regex/UTF-16, structured constants, metadata, ordered unions, transforms, volatile placement, recursive/shared/lazy graphs and builder errors/cache. This is the private engine carrier, not live Loader/Python graph acceptance.',
        extra_inputs=[Path(__file__).resolve(), ROOT / 'dsh/boot/config_projection_current.py', *resources.iterdir()])
