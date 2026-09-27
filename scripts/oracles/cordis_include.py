"""Actual Include refresh queue, with a gated builtin plugin and real JSON file."""
import asyncio
import json
import tempfile
from pathlib import Path

from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.cordis.include import Include
from dsh.cordis.plugin import Plugin


async def scenario(number):
    ctx, log = Context(), []
    entered, finish = asyncio.Event(), asyncio.Event()
    state = {}
    class ObservedInclude(Include):
        def __init__(self, c, config=None):
            super().__init__(c, config)
            state['include'] = self
    class Probe(Plugin):
        name = 'probe'
        async def apply(self, c, config=None):
            value = config['value']
            log.append('start:' + str(value))
            if value == (1 if number in (39, 40, 41) else 2):
                entered.set()
                await finish.wait()
                if number in (38, 40):
                    log.append('reject:' + str(value))
                    raise RuntimeError('probe rejected ' + str(value))
            log.append('ready:' + str(value))
            return lambda: log.append('stop:' + str(value))
    with tempfile.TemporaryDirectory(prefix='cordis-include-') as directory:
        filename = Path(directory) / 'config.json'
        def write(value):
            filename.write_text(json.dumps([{'id': 'one', 'name': 'cordis:probe', 'config': {'value': value}}]), encoding='utf-8')
        try:
            ctx.baseUrl = Path(directory).as_uri() + '/'
            await ctx.plugin(Loader)
            if number in (48, 49, 50, 51):
                class Lifecycle(Plugin):
                    name = 'handle-lifecycle'
                    inject = ['gate'] if number >= 50 else []
                    def apply(self, c, config=None):
                        log.append('start:' + str(config['value']))
                        return lambda: log.append('stop:' + str(config['value']))
                handle = ctx.plugin(Lifecycle, {'value': 1})
                raw = handle.ctx.fiber
                target = handle if number in (48, 50) else raw
                if number < 50:
                    await handle
                    await target.restart()
                else:
                    target.update({'value': 2})
                    ctx.provide('gate', True)
                    await target.await_settled()
                observation = {'log': log[:], 'states': [handle.state, raw.state],
                               'configs': [handle.config['value'], raw.config['value']]}
                await ctx.fiber.dispose()
                observation['finalLog'] = log[:]
                observation['disposed'] = [handle.state, raw.state]
                return observation
            if number in (46, 47):
                class Recovery(Plugin):
                    name = 'handle-recovery'
                    def apply(self, c, config=None):
                        log.append(config['value'])
                        if config['value'] == 'bad':
                            raise RuntimeError('bad config')
                handle = ctx.plugin(Recovery, {'value': 'bad'})
                async def error_of(operation):
                    try:
                        await operation
                    except Exception as error:
                        return str(error)
                    return None
                initial = await error_of(handle)
                raw = handle.ctx.fiber
                target = handle if number == 46 else raw
                target.update({'value': 'good'})
                recovered = await error_of(target.await_settled())
                original = await error_of(handle)
                method_error = await error_of(handle.await_settled())
                observation = {'initial': initial, 'recovered': recovered, 'original': original,
                               'methodError': method_error, 'log': log[:],
                               'states': [handle.state, raw.state],
                               'configs': [handle.config['value'], raw.config['value']]}
                await ctx.fiber.dispose()
                observation['disposed'] = [handle.state, raw.state]
                return observation
            if number == 45:
                class HandleIdentity(Plugin):
                    name = 'handle-identity'
                    async def apply(self, c, config=None):
                        if config['value'] == 2:
                            entered.set()
                            await finish.wait()
                handle = ctx.plugin(HandleIdentity, {'value': 1})
                raw = await handle
                identity = {'same': handle is raw, 'contextOwnsRaw': handle.ctx.fiber is raw}
                updating = handle.update({'value': 2})
                await entered.wait()
                pending = {'handle': handle.state, 'raw': raw.state}
                finish.set()
                await updating
                await handle.dispose()
                return {'identity': identity, 'pending': pending, 'final': {'handle': handle.state, 'raw': raw.state}}
            if number == 44:
                class PublicDispose(Plugin):
                    name = 'public-dispose'
                    def apply(self, c, config=None):
                        async def cleanup():
                            log.append('cleanup-enter')
                            entered.set()
                            await finish.wait()
                            log.append('cleanup-exit')
                        return cleanup
                fiber = await ctx.plugin(PublicDispose)
                first = asyncio.ensure_future(fiber.dispose())
                await entered.wait()
                second_done = False
                async def observe_second():
                    nonlocal second_done
                    await fiber.dispose()
                    second_done = True
                    log.append('second-complete')
                second = asyncio.create_task(observe_second())
                await asyncio.sleep(0.05)
                pending = {'secondDone': second_done, 'log': log[:]}
                finish.set()
                await asyncio.gather(first, second)
                return {'pending': pending, 'log': log, 'final': fiber.state}
            if number == 43:
                class Reject(Plugin):
                    name = 'reject'
                    def apply(self, c, config=None):
                        log.append('reject:' + str(config['value']))
                        raise RuntimeError('rejected ' + str(config['value']))
                ctx.get('loader').builtins['reject'] = Reject
                filename.write_text(json.dumps([
                    {'id': 'row' + str(value), 'name': 'cordis:reject', 'config': {'value': value}}
                    for value in (1, 2)
                ]), encoding='utf-8')
                fiber = ctx.plugin(ObservedInclude, {'path': filename.as_uri()})
                errors = []
                try:
                    await fiber.await_settled()
                except Exception as error:
                    errors = [str(item) for item in error.errors]
                include = state['include']
                await include.await_()
                observation = {'errors': errors, 'state': fiber.state, 'data': include.data,
                               'content': include.content, 'rows': include.root.data, 'log': log[:]}
                await ctx.fiber.dispose()
                observation['final'] = fiber.state
                return observation
            ctx.get('loader').builtins['probe'] = Probe
            write(1)
            fiber = ctx.plugin(ObservedInclude, {'path': filename.as_uri()})
            async def outcome(operation):
                try:
                    await operation
                except Exception as error:
                    return str(error)
                return None
            if number == 40:
                result = asyncio.create_task(outcome(fiber.await_settled()))
                await entered.wait()
                finish.set()
                error = await result
                include = state['include']
                observation = {'error': error, 'state': fiber.state, 'data': include.data,
                               'content': include.content, 'rows': include.root.data, 'log': log[:]}
                await fiber.dispose()
                observation['final'] = fiber.state
                return observation
            if number in (41, 42):
                if number == 42:
                    await fiber.await_settled()
                    write(2)
                    operation = state['include'].refresh()
                else:
                    operation = fiber.await_settled()
                result = asyncio.create_task(outcome(operation))
                await entered.wait()
                include = state['include']
                done = False
                async def dispose():
                    nonlocal done
                    await fiber.dispose()
                    done = True
                    log.append('dispose-complete')
                disposal = asyncio.create_task(dispose())
                await asyncio.sleep(0.05)
                pending = {'done': done, 'log': log[:]}
                finish.set()
                error = await result
                await disposal
                return {'pending': pending, 'error': error, 'final': fiber.state, 'log': log, 'entries': list(include.store)}
            if number == 39:
                await entered.wait()
                include = state['include']
                write(2)
                refresh = asyncio.create_task(include.refresh())
                await asyncio.sleep(0.05)
                pending = log[:]
                finish.set()
                await asyncio.gather(fiber.await_settled(), refresh)
                after = log[:]
                committed = include.root.data[0]['config']['value']
                await fiber.dispose()
                return {'pending': pending, 'after': after, 'committed': committed, 'disposed': log[:]}
            await fiber.await_settled()
            include = state['include']
            async def observe():
                try:
                    await include.refresh()
                except Exception as error:
                    return str(error)
                return None
            write(2)
            first = asyncio.create_task(observe())
            await entered.wait()
            write(3)
            second = asyncio.create_task(observe())
            pending = log[:]
            finish.set()
            errors = await asyncio.gather(first, second)
            committed = include.root.data[0]['config']['value']
            after = log[:]
            await fiber.dispose()
            return {'pending': pending, 'after': after, 'errors': errors, 'committed': committed, 'disposed': log[:]}
        finally:
            finish.set()
            await ctx.fiber.dispose()
