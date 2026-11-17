"""Mounted current Session-log upload defaults, limits and reversible exclusions."""
import asyncio
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return ['default', 'disabled', 'toggle', 'exclude', 'purpose', 'throw',
            'blocked', 'exact', 'below', 'prefix', 'unload', 'owner']


async def observe():
    from dsh.cordis.context import Context
    from dsh.cordis.awaiting import await_callback_result
    from dsh.cordis.json_text import stringify_json
    from dsh.core.abort import AbortSignal
    from dsh.core.runtime_v4 import SessionV4Plugin
    from dsh.llm.deepseek_api_extensions_current import CurrentDeepSeekLlmApiExtensions
    from dsh.session.session_log_deepseek_current import CurrentSessionLogDeepSeekPlugin
    rows = []
    with patch('time.time', return_value=1):
        for case in cases():
            ctx = Context(); warnings = []; uploads = []; results = []
            ctx.logger.warn = lambda text, *args: warnings.append(str(text))
            await ctx.plugin(SessionV4Plugin)
            await ctx.plugin(CurrentDeepSeekLlmApiExtensions)
            session = ctx.sessions.create('upload')
            for index in range(2):
                session.append('user/message', dict(id='message-' + str(index), role='user', source=dict(kind='user'),
                    content=[dict(type='text', text='文旦🍐')]), surface_op='append')
            first = dict(version=1, sessionFormatVersion=4, session=dict(version=4, id='upload', createdAt=1000),
                         afterSeq=-1, throughSeq=0, events=[session.snapshotEvents()[0]])
            limit = len(stringify_json(first).encode('utf-8'))
            config = {}
            if case in ['disabled', 'toggle']: config['enabled'] = False
            if case == 'blocked': config['maxBytes'] = 1
            if case in ['exact', 'prefix']: config['maxBytes'] = limit
            if case == 'below': config['maxBytes'] = limit - 1
            fiber = await ctx.plugin(CurrentSessionLogDeepSeekPlugin, config)
            service = ctx.sessionLogDeepSeek
            def exclude(upload):
                uploads.append(dict(upload))
                if case == 'throw': raise ValueError('controlled exclusion')
                return case in ['exclude', 'owner'] or upload.get('purpose') == 'title'
            disposer = service.registerExclusion(exclude) if case in ['exclude', 'purpose', 'throw'] else None
            owner = None
            if case == 'owner':
                def caller(child): child.sessionLogDeepSeek.registerExclusion(exclude)
                caller.inject = ['sessionLogDeepSeek']
                owner = await ctx.plugin(caller)
            async def prepare(purpose=None):
                request = dict(sessionId='upload', body={}, signal=AbortSignal())
                if purpose is not None: request['purpose'] = purpose
                prepared = await ctx.deepseekLlmApiExtensions.prepare(request)
                results.append(json.loads(stringify_json(prepared.fields)))
                return prepared
            try:
                prepared = await prepare('title' if case == 'purpose' else None)
                if case == 'prefix': await prepared.accept()
                if case == 'toggle': await await_callback_result(fiber.update(dict(enabled=True)))
                if disposer: await await_callback_result(disposer())
                if owner: await owner.dispose()
                if case == 'unload': await fiber.dispose()
                await prepare()
                rows.append(dict(case=case, results=results, uploads=uploads, warnings=warnings,
                                 events=session.snapshotEvents(), mounted=ctx.get('sessionLogDeepSeek', False) is not None))
            finally:
                await ctx.fiber.dispose()
    return json.loads(stringify_json(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_session_log_upload.mts', __doc__,
        [Path(__file__).resolve(), ROOT / 'dsh/session/session_log_deepseek_current.py'])
