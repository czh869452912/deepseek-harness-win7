"""Isolated installed-product host for original Schedule and Discover journeys.

Run with the extracted interpreter's -I -B flags. Browser/fixture orchestration
is external; every dsh import must resolve inside the actual product.
"""
import asyncio
import faulthandler
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote


async def main(config):
    import dsh
    from dsh.boot.profile import init_profile, PROFILE_TEMPLATES
    from dsh.boot.profile_boot import run_profile
    from dsh.core.abort import AbortController
    root = Path(sys.executable).resolve().parent
    assert root in Path(dsh.__file__).resolve().parents
    output, home = Path(config['output']), Path(config['home'])
    previous = json.loads(Path(config['previous']).read_text(encoding='utf-8')) if config.get('previous') else None
    if config['kind'] == 'market' and previous is None:
        init_profile(str(home / 'profiles/web'), PROFILE_TEMPLATES['web']['bundles'] +
                     ['@deepseek-ai/dsh-experimental-plugin-market-bundle'])
    if config['kind'] == 'market':
        # Explicit loopback HTTP fixture for repository Markdown/images only.
        # Registry, loader, service bindings and application assets are genuine.
        import dsh.util.plugin_detail_http as detail
        fetch = detail.fetch_body
        async def redirect(url, maximum, signal, options):
            return await fetch(config['fixture'] + '/files?url=' + quote(url, safe=''), maximum, signal, options)
        detail.fetch_body = redirect
    app = await run_profile(dict(profile='web', dshHome=str(home),
        args=['--no-open', '--host', '127.0.0.1', '--port', '0'], waitForExit=False))
    ctx = app['ctx']
    report = dict(kind=config['kind'], processId=os.getpid(), cold=previous is not None, steps=[],
                  runtime=dict(root=str(root), executable=str(Path(sys.executable).resolve()), python=sys.version))
    async def monitor():
        def chain(coro):
            frames = []
            seen = set()
            while coro is not None and id(coro) not in seen:
                seen.add(id(coro))
                frame = getattr(coro, 'cr_frame', getattr(coro, 'gi_frame', None))
                if frame is not None:
                    frames.append(dict(file=frame.f_code.co_filename, line=frame.f_lineno,
                                       name=frame.f_code.co_name))
                    if frame.f_code.co_name == 'resume_coroutine':
                        frames.extend(chain(frame.f_locals.get('listener')))
                coro = getattr(coro, 'cr_await', getattr(coro, 'gi_yieldfrom', None))
            return frames
        while True:
            await asyncio.sleep(5)
            rows = {}
            for task in asyncio.all_tasks():
                key = json.dumps(chain(task.get_coro()), sort_keys=True)
                rows[key] = rows.get(key, 0) + 1
            with (output / 'tasks.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps([dict(count=count, chain=json.loads(key))
                                         for key, count in rows.items()]) + '\n')
    monitoring = asyncio.create_task(monitor())
    stacks = (output / 'thread-stacks.log').open('w', encoding='utf-8')
    faulthandler.dump_traceback_later(20, repeat=True, file=stacks)
    try:
        class Adapter:
            async def resolve_model(self, provider, model, signal=None):
                return dict(provider=provider, id=model, name=model, context=dict(contextWindow=131072))
            async def stream(self, request):
                report.setdefault('modelRequests', []).append(dict(provider=request['provider'], model=request['model']))
                yield dict(type='block-start', index=0, blockType='text')
                yield dict(type='text-delta', index=0, text='Scheduled work completed.')
                yield dict(type='finish', reason=dict(kind='stop'))
        ctx.llm.registerAdapter(['script'], Adapter())
        await ctx.agentDefaultModel.saveSelection(dict(provider='script', model='model'))
        sid = 'candidate-minimal'
        if previous is None:
            report['presets'] = []
            for preset in ['minimal', 'standard', 'ptc', 'cordis']:
                identity = 'candidate-' + preset
                await ctx.sessionController.create(dict(sessionId=identity, cwd=str(home), agentPreset=preset))
                agent = ctx.agents.get(identity)
                names = [row['name'] for row in ctx.tools.schemas(agent)]
                report['presets'].append(dict(id=preset, tools=names))
                if preset == 'cordis':
                    assert {'cordis_inspect_list', 'cordis_inspect_query'} <= set(names)
            batch = await ctx.tools.execute(dict(agent=ctx.agents.get('candidate-ptc'), signal=AbortController().signal,
                calls=[dict(type='tool-call', id='installed-ptc', name='run_code', arguments=json.dumps(dict(
                    code='return await tools.schedule_list({})', description='Read installed Schedule through Python SDK')))]))
            execution = batch['results'][0]['result']
            assert not execution.is_error, execution.error
            report['ptc'] = dict(language=ctx.ptcRuntime.language, isError=execution.is_error, value=execution.value)
            agent = ctx.agents.get(sid)
            from dsh.llm.message import create_user_message
            agent.followup(create_user_message(dict(content=[dict(type='text', text='Installed application fixture')], source=dict(kind='user'))))
            await asyncio.wait_for(agent.whenIdle(), 15)
            await ctx.sessionController.rename(dict(sessionId=sid, title=sid))
            await agent.session.flush()
        else:
            assert previous['processId'] != os.getpid() and ctx.agents.get(sid) is None
            report['steps'].append('new-process-session-not-live-before-browser')
        if config['kind'] == 'schedule':
            if previous is None:
                task = await ctx.schedule.create(dict(title='Browser Schedule contract', prompt='Perform the browser check',
                    timing=dict(kind='after', after_seconds=3600), target=dict(kind='session', sessionId=sid)), sid)
            else:
                task = await ctx.schedule.view(dict(id=previous['task']['id']))
                assert {k:v for k,v in task.items() if k != 'deliveryFloorEndsAt'} == {
                    k:v for k,v in previous['task'].items() if k != 'deliveryFloorEndsAt'}
                observed = await ctx.sessionQuery.observeSession(task['lastDelivery']['targetSessionId'], dict(projectionMode='none'))
                try:
                    assert any(e['type'] == 'user/message' and e['data']['id'] == task['lastDelivery']['messageId'] for e in observed.events)
                finally: observed.dispose()
                report['steps'].append('saved-task-and-delivery-read-before-browser')
        elif previous is not None:
            report['indexesBefore'] = ctx.pluginMarket.listIndexes()
            assert report['indexesBefore'] == [dict(url=row['url']) for row in previous['indexes']]
            report['steps'].append('saved-market-index-read-before-browser')
        browser = dict(url=ctx.connection.authenticatedUrl(ctx.webServer.getOrigin()), cold=previous is not None,
                       browser=config['browser'], currentOnboarding=False)
        if config['kind'] == 'schedule': browser['task'] = task['id']
        else: browser['index'] = config['fixture'] + '/index.json'
        (output / 'browser-config.json').write_text(json.dumps(browser), encoding='utf-8')
        print('CURRENT_APPLICATION_READY', flush=True)
        command = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
        assert command.strip() == 'finish'
        observation = json.loads((output / 'browser-observations.json').read_text(encoding='utf-8'))
        assert observation['passed'], observation.get('failure')
        if config['kind'] == 'schedule':
            task = await ctx.schedule.view(dict(id=task['id']))
            assert task['title'] == ('Browser Schedule cold edited' if previous else 'Browser Schedule edited')
            assert task['status'] == 'active'
            receipt = task['lastDelivery']; agent = ctx.agents.get(receipt['targetSessionId'])
            await asyncio.wait_for(agent.whenIdle(), 15); await ctx.sessions.flush(agent.session)
            observed = await ctx.sessionQuery.observeSession(agent.id, dict(projectionMode='none'))
            try:
                messages = [e for e in observed.events if e['type'] == 'user/message' and e['data'].get('source', {}).get('kind') == 'schedule']
                report.update(task=task, messages=messages, events=list(observed.events),
                              history=await ctx.schedule.history(dict(id=task['id'], limit=10)))
                delivery_ids = {row['messageId'] for row in report['history']['records']}
                deliveries = [e for e in messages if e['data']['id'] in delivery_ids]
                report['deliveries'] = deliveries
                assert len(delivery_ids) == len(deliveries) == (2 if previous else 1)
                assert sum(e['data']['id'] == receipt['messageId'] for e in messages) == 1
            finally: observed.dispose()
        else:
            report['indexes'] = ctx.pluginMarket.listIndexes()
            assert report['indexes'] == [dict(url=config['fixture'] + '/index.json', title='Browser Market')]
        report['steps'].append('original-browser-persisted-real-application-state')
        report['modules'] = {}
        for module in list(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename and getattr(module, '__name__', '').startswith(('dsh.', 'apps.')):
                path = Path(filename).resolve()
                assert root in path.parents, str(path)
                report['modules'][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        report['passed'] = True
    finally:
        faulthandler.cancel_dump_traceback_later(); stacks.close()
        monitoring.cancel(); await asyncio.gather(monitoring, return_exceptions=True)
        app['shutdown'].shutdown(0); await app['shutdown'].wait()
        (output / 'host-observations.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))))
