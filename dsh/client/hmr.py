"""Original client bundle stat-poll and graph/rebuilt SSE protocol."""
import asyncio
import json
import logging
import os

from dsh.cordis.plugin import Plugin


def stat_bundle(path):
    value = os.stat(path)
    return dict(mtimeMs=value.st_mtime * 1000.0, size=value.st_size)


class ClientHmrPlugin(Plugin):
    id = 'client-hmr'
    inject = ['clientModules', 'webServer']

    def apply(self, ctx):
        interval = self.config.get('pollIntervalMs', 500)
        if type(interval) is not int or interval < 1:
            raise ValueError('client-hmr: pollIntervalMs must be a positive integer')
        modules, server = ctx.get('clientModules'), ctx.get('webServer')
        watched, clients, active = {}, {}, set()
        stopped = asyncio.Event()
        def rehash(identity, watch, current):
            try:
                modules.rebuilt(identity)
            except FileNotFoundError:
                watch['dirty'] = True
                return
            except Exception as error:
                logging.getLogger('client-hmr').warning('%s', error)
            watch.update(current, dirty=False)
        def check(identity, watch):
            try:
                current = stat_bundle(watch['path'])
            except OSError as error:
                watch['dirty'] = True
                if not isinstance(error, FileNotFoundError):
                    logging.getLogger('client-hmr').warning('%s', error)
                return
            if watch['dirty'] or any(current[key] != watch[key] for key in current):
                rehash(identity, watch, current)
        def sync():
            rows = {row['id']: modules.artifact_baseline(row['id']) for row in modules.graph()['entries']}
            rows = {key: value for key, value in rows.items() if value is not None}
            for identity in list(watched):
                if rows.get(identity, {}).get('path') != watched[identity]['path']:
                    del watched[identity]
            for identity, baseline in rows.items():
                if identity not in watched:
                    watched[identity] = dict(baseline, dirty=False)
                    check(identity, watched[identity])
        sync()
        unsubscribe_graph = modules.on_graph_changed(sync)
        ctx.effect(lambda: unsubscribe_graph)
        async def poll():
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), interval / 1000)
                except asyncio.TimeoutError:
                    for identity, watch in list(watched.items()):
                        check(identity, watch)
        def rebuilt(identity, revision):
            frame = dict(type='rebuilt', id=identity, rev=revision)
            for queue in list(clients.values()):
                queue.put_nowait(frame)
        unsubscribe_rebuilt = modules.rebuild_listener(rebuilt)
        ctx.effect(lambda: unsubscribe_rebuilt)
        async def handler(request, response):
            if request['method'] not in ('GET', 'HEAD'):
                response.write_status(405)
                await response.finish()
                return
            active.add(asyncio.current_task())
            queue = asyncio.Queue()
            clients[response] = queue
            async def send(frame):
                await response.write_chunk(('data: ' + json.dumps(frame, ensure_ascii=False, separators=(',', ':')) + '\n\n').encode('utf-8'))
            disconnect = asyncio.create_task(request['reader'].read())
            pending = None
            try:
                response.write_status(200)
                for key, value in (('content-type', 'text/event-stream'), ('cache-control', 'no-cache'), ('connection', 'keep-alive')):
                    response.write_header(key, value)
                await response.write_chunk(b': connected\n\n')
                await send(dict(type='graph', graph=modules.graph()))
                while not stopped.is_set():
                    pending = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait([pending, disconnect], return_when=asyncio.FIRST_COMPLETED)
                    if disconnect in done:
                        break
                    frame = pending.result()
                    pending = None
                    if frame is None:
                        break
                    await send(frame)
            finally:
                clients.pop(response, None)
                disconnect.cancel()
                if pending is not None:
                    pending.cancel()
                await asyncio.gather(*([disconnect] + ([pending] if pending is not None else [])), return_exceptions=True)
                response.writer.close()
                active.discard(asyncio.current_task())
        remove_route = server.register('exact', '/plugins/events', handler)
        ctx.effect(lambda: remove_route)
        task = asyncio.create_task(poll())
        async def close():
            stopped.set()
            remove_route()
            unsubscribe_graph()
            unsubscribe_rebuilt()
            for response, queue in list(clients.items()):
                queue.put_nowait(None)
                response.writer.close()
            await asyncio.gather(task, *list(active), return_exceptions=True)
            watched.clear()
        ctx.effect(lambda: close)
