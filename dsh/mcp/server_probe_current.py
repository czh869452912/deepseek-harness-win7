"""One-shot, bounded server inspection independent of the application registry."""
import math
import time

from dsh.mcp.client_current import CurrentSdkClient
from dsh.mcp.credentials_current import McpTemplateBinding
from dsh.mcp.generation_current import McpGeneration


def resolve_probe_options(options):
    result = dict(timeoutMs=10000, maxPages=16, maxToolNames=512)
    for key in result:
        if options.get(key) is not None:
            result[key] = options[key]
    value = result['timeoutMs']
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise TypeError('probeServer: timeoutMs must be a positive finite number')
    for key in ('maxPages', 'maxToolNames'):
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 1 or value > 9007199254740991 or int(value) != value:
            raise TypeError('probeServer: '+key+' must be a positive safe integer')
    result['signal'] = options.get('signal')
    return result


async def probe_server(ctx, config, options=None):
    spec = resolve_probe_options(options or {})
    started = time.time()*1000
    remaining = lambda: spec['timeoutMs']-(time.time()*1000-started)
    duration = lambda: int(time.time()*1000)-int(started)
    binding = McpTemplateBinding(ctx, config)
    client = CurrentSdkClient('dsh-mcp-probe')
    generation = McpGeneration(client, config.get('closeTimeoutMs',5000), lambda error: binding.diagnostic(error,'cleanup'))
    signal = spec['signal']
    def abort(_=None):
        generation.close()
    detach = signal.add_listener('abort', abort) if signal is not None else lambda: None
    stage = 'connect'
    try:
        resolved = await generation.run(binding.resolve, remaining())
        await generation.connect(resolved, remaining())
        identity = client.getServerVersion()
        stage = 'list'
        names, truncated, cursor = [], False, None
        if 'tools' in (client.getServerCapabilities() or {}):
            for page in range(int(spec['maxPages'])):
                packet = dict(method='tools/list')
                if cursor is not None:
                    packet['params'] = dict(cursor=cursor)
                response = await generation.run(lambda current: client.request(packet, dict(signal=current)), remaining())
                for tool in response['tools']:
                    if len(names) >= spec['maxToolNames']:
                        truncated = True
                        break
                    names.append(tool['name'])
                cursor = response.get('nextCursor')
                if cursor is None or truncated:
                    break
                if page == spec['maxPages']-1:
                    truncated = True
        result = dict(ok=True, toolNames=names, truncated=truncated, durationMs=duration())
        if identity is not None:
            result['serverInfo'] = dict(name=identity['name'],version=identity['version'])
    except Exception as error:
        result = dict(ok=False,stage=stage,message='probe aborted' if signal is not None and signal.aborted else binding.diagnostic(error,stage),durationMs=duration())
    finally:
        detach()
        closure = await generation.close()
    result.update(closure)
    return result
