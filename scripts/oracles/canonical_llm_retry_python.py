import argparse
import asyncio
import copy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading


NAMES = ('recover', 'exhaust', 'unauthorized', 'retry-after', 'empty', 'partial-eof', 'disabled-thinking', 'partial-tool', 'cancel-backoff')


async def observe(name):
    from dsh.cordis.context import Context
    from dsh.cordis.environment import LaunchEnvironmentSnapshot
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.agent import AgentOptions
    from dsh.core.tools import ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.llm.llm_service import LlmRuntime
    from dsh.llm.llm_deepseek import DeepSeekAdapter
    from dsh.llm.llm_retry import LLMRetryPlugin
    requests, executed = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(dict(body=body, authorization=self.headers.get('authorization')))
            status = 401 if name == 'unauthorized' else 503 if name in ('exhaust', 'retry-after', 'cancel-backoff') or name == 'recover' and len(requests) == 1 else 200
            payload = 'data: {"choices":[{"delta":{"content":"recovered"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n' if status == 200 else json.dumps(dict(error=dict(message='fixture failure')))
            if name == 'empty' and len(requests) == 1:
                payload = 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
            if name == 'partial-eof':
                payload = 'data: {"choices":[{"delta":{"content":"discarded"},"finish_reason":null}]}\n\n'
            if name == 'partial-tool' and len(requests) <= 2:
                delta = dict(tool_calls=[dict(index=0, id='discarded-call' if len(requests) == 1 else 'accepted-call',
                    type='function', function=dict(name='danger', arguments='{}'))])
                payload = 'data: ' + json.dumps(dict(choices=[dict(delta=delta, finish_reason='tool_calls')])) + '\n\n'
                payload += 'data: {broken}\n\n' if len(requests) == 1 else 'data: [DONE]\n\n'
            encoded = payload.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            if name == 'retry-after':
                self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    worker.start()
    ctx = Context()
    ctx.set_service('launchEnvironment', LaunchEnvironmentSnapshot([dict(source='process', values=dict(DEEPSEEK_API_KEY='fixture-key'))]))
    for plugin in (LlmRuntime, ToolsPlugin, SystemPrompt, LLMRetryPlugin, AgentLoopPlugin):
        await ctx.plugin(plugin)
    delay = 1000 if name == 'cancel-backoff' else 1
    config = dict(baseURL='http://127.0.0.1:' + str(server.server_port), streamIdleTimeoutMs=3000,
        retryPolicy=dict(mode='normal', maxRetries=2, backoff=dict(initialDelayMs=delay, maxDelayMs=max(delay, 10), jitterRatio=0)))
    if name == 'partial-tool':
        config['retryPolicy']['retryableCodes'] = ['MALFORMED_RESPONSE']
    if name == 'disabled-thinking':
        config['thinking'] = 'disabled'
    adapter = DeepSeekAdapter(ctx, config)
    adapter.user_id = 'fixture-user'
    ctx.get('llm').register_adapter(['deepseek-official'], adapter)
    async def danger(arguments, execution):
        executed.append('danger')
        return dict(executed=True)
    if name == 'partial-tool':
        ctx.get('tools').register(dict(name='danger', description='Observe accepted execution',
            parameters=dict(type='object', properties={}, additionalProperties=False), execute=danger,
            output=dict(schema=dict(type='object', properties=dict(executed=dict(type='boolean')), required=['executed'], additionalProperties=False),
                render=lambda *_: [dict(type='text', text='executed')])))
    parent = await ctx.get('agent_loop').create('retry-session', options=AgentOptions(provider='deepseek-official',
        model='model', reasoning_effort='high' if name == 'disabled-thinking' else None))
    if name == 'cancel-backoff':
        ctx.on('session/event', lambda session, event: parent.agent.cancel(dict(kind='user')) if session is parent.agent.session and event['type'] == 'llm/retry' else None)
    try:
        parent.agent.followup('retry request')
        await asyncio.wait_for(parent.agent.when_idle(), 10)
        events = [dict(type=event['type'], data=copy.deepcopy(event['data'])) for event in parent.agent.session.events]
        expected = dict(recover=2, exhaust=3, unauthorized=1, empty=2, **{'retry-after':1, 'partial-eof':1, 'disabled-thinking':0, 'partial-tool':3, 'cancel-backoff':1})
        assert len(requests) == expected[name]
        assert events[-1]['type'] == 'turn/end'
        assert executed == (['danger'] if name == 'partial-tool' else [])
        return dict(name=name, requests=requests, executed=executed, events=events, messages=parent.agent.session.derive_messages())
    finally:
        await parent.dispose()
        await adapter.close()
        await ctx.fiber.dispose()
        server.shutdown()
        server.server_close()
        worker.join(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    sys.path.insert(0, str(root))
    rows = [asyncio.run(observe(name)) for name in NAMES]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, modules=modules, rows=rows), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
