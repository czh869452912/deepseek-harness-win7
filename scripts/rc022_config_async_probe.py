"""Compare the sequential asynchronous adapter to the original synchronous Source."""
from pathlib import Path
from scripts import rc022_config_projection_probe as graphs


async def observe():
    return await graphs.observe_mode(True)


if __name__ == '__main__':
    graphs.probe.native = observe
    resources = graphs.ROOT / 'dsh/boot/config-projection'
    graphs.probe.main('rc022_config_projection.mts', prepare=graphs.prepare,
        scope='Sequential async projector adaptation versus original synchronous fixed Source across 180 actual Source Schema graphs. No concurrent traversal; direct lazies, cache/errors, defaults and all prior pure engine constraints.',
        extra_inputs=[Path(__file__).resolve(),Path(graphs.__file__).resolve(),
            graphs.ROOT/'dsh/boot/config_projection_current.py',*resources.iterdir()])
