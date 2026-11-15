"""Stateless Python/process implementation of the current ptcRuntime seam.

This provider does not advertise file confinement. Explicit policies are
rejected; it must not replace a confining provider by implicit fallback.
"""
import math
import os

from dsh.code_runtime.process import PythonProcessRuntime
from dsh.cordis.schema import Schema
from dsh.core.timeout import clamp_timeout

DEFAULTS = dict(timeoutMs=120000, maxTimeoutMs=600000,
                maxOutputBytes=67108864, maxOldGenerationSizeMb=512)


class PythonPtcRuntime(PythonProcessRuntime):
    service_name = 'ptcRuntime'
    programFormat = 'function-body'
    retainsState = False
    sandboxMode = None
    executionInstructions = (
        'The program is the body of an async Python 3.8 function. Top-level await '
        'and return are supported. Emit output with print(...) or return a lossless '
        'JSON value. Only printed values and the returned value become program '
        'output. Each call runs in a fresh Python process. Python modules are '
        'available through import. Relative paths use the supplied working '
        'directory; os.environ starts empty. This provider does not confine direct '
        'filesystem access.')
    Config = Schema.object({key: Schema.number().default(value) for key, value in DEFAULTS.items()})

    def __init__(self, ctx, config=None):
        config = dict(DEFAULTS, **(config or {}))
        unknown = set(config) - set(DEFAULTS)
        if unknown:
            raise ValueError('ptc-runtime-python: unsupported config ' + ', '.join(sorted(unknown)))
        for key, value in config.items():
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('ptc-runtime-python: %s must be a positive finite number' % key)
        if config['maxTimeoutMs'] > 2147483647:
            raise ValueError('ptc-runtime-python: maxTimeoutMs exceeds timer bound')
        self.ptc_config = config
        self.default_cwd = os.path.abspath(os.getcwd())
        super().__init__(ctx, dict(maxWallMs=config['maxTimeoutMs'], computeMs=60000,
            maxOutputBytes=config['maxOutputBytes'], maxOldGenerationSizeMb=config['maxOldGenerationSizeMb']))

    @property
    def timeout(self):
        return dict(defaultMs=min(self.ptc_config['timeoutMs'], self.ptc_config['maxTimeoutMs']),
                    maxMs=self.ptc_config['maxTimeoutMs'])

    def resolve(self, request):
        if self.closed:
            raise RuntimeError('ptc-runtime-python: resolve after disposal')
        if 'sandboxPolicy' in request:
            raise ValueError('ptc-runtime-python: sandboxPolicy is unsupported without confinement')
        cwd = request.get('cwd', self.default_cwd)
        if not isinstance(cwd, str) or not os.path.isabs(cwd):
            raise ValueError('ptc-runtime-python: cwd must be absolute')
        timeout = (None if 'timeoutMs' in request and request['timeoutMs'] is None
            else clamp_timeout(request.get('timeoutMs'), self.ptc_config['timeoutMs'],
                               self.ptc_config['maxTimeoutMs'], 'ptc-runtime-python: timeoutMs'))
        return dict(request, cwd=cwd, timeoutMs=timeout)

    async def run(self, spec):
        if self.closed:
            raise RuntimeError('ptc-runtime-python: run after disposal')
        if 'sandboxPolicy' in spec:
            raise ValueError('ptc-runtime-python: sandboxPolicy is unsupported without confinement')
        cwd, timeout = spec.get('cwd'), spec.get('timeoutMs')
        if (not isinstance(cwd, str) or not os.path.isabs(cwd) or 'timeoutMs' not in spec
                or (timeout is not None and (type(timeout) not in (int, float)
                    or not math.isfinite(timeout) or timeout <= 0 or timeout > self.ptc_config['maxTimeoutMs']))):
            raise ValueError('ptc-runtime-python: run requires resolved cwd and timeout')
        return await super().run(spec)

    async def release(self, owner):
        # Stateless providers deliberately ignore exact-object stateOwner.
        pass

    def _run_limits(self, request):
        return dict(self.config, maxWallMs=request['timeoutMs'], computeMs=None)

    def _process_cwd(self, request):
        return request['cwd']
