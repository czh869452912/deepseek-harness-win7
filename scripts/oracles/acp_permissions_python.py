import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.acp.rpc import AcpRpc
from dsh.acp.server import AcpPlugin
from dsh.acp.session_runtime import AcpSession
from dsh.cordis.context import Context
from dsh.core.abort import AbortSignal
from dsh.core.session import Session, SessionStore
from dsh.interaction.user_approval import ApprovalService


RESPONSES = [
    ('allow', {'outcome': {'outcome': 'selected', 'optionId': 'allow-once'}}),
    ('reject', {'outcome': {'outcome': 'selected', 'optionId': 'reject-once'}}),
    ('unknown-option', {'outcome': {'outcome': 'selected', 'optionId': 'allow-always'}}),
    ('cancelled', {'outcome': {'outcome': 'cancelled'}}),
    ('unknown-kind-allow', {'outcome': {'outcome': 'unknown', 'optionId': 'allow-once'}}),
    ('missing-kind-allow', {'outcome': {'optionId': 'allow-once'}}),
    ('missing-outcome', {}), ('null-response', None), ('remote-error', None),
    ('same-id-foreign', None), ('missing-call-id', None), ('pre-abort', None),
]


async def observe():
    rows = []
    for mode, response in RESPONSES:
        ctx = Context()
        service, bridge = ApprovalService(ctx), AcpPlugin()
        bridge.apply(ctx)
        session = Session('00000000-0000-4000-8000-000000000001', ctx=ctx)
        detach = SessionStore(ctx).enter(session)
        owned = SimpleNamespace(id=session.id, session=session)
        requests, updates, order = [], [], []
        def write(frame):
            packet = json.loads(frame)
            if packet['method'] == 'session/update':
                updates.append(packet['params'])
            else:
                requests.append(packet['params'])
                order.append(bool(updates) and updates[-1]['update']['sessionUpdate'] == 'tool_call')
                reply = {'jsonrpc': '2.0', 'id': packet['id']}
                if mode == 'remote-error':
                    reply['error'] = {'code': -32603, 'message': 'client gone'}
                else:
                    reply['result'] = response
                bridge.connection.data(json.dumps(reply) + '\n')
        bridge.connection = AcpRpc(write)
        record = AcpSession(owned, ctx=ctx, notify=lambda params: bridge.connection.notify('session/update', params))
        bridge.sessions[session.id] = record
        try:
            session.append('turn/start', {'turn': 1})
            session.append('step/start', {'turn': 1, 'step': 1})
            session.append('tool/call', {'turn': 1, 'step': 1, 'callId': 'call-9', 'name': 'bash', 'arguments': '{}'})
            agent = SimpleNamespace(id=session.id, session=session) if mode == 'same-id-foreign' else owned
            request = {'agent': agent, 'toolName': 'bash'}
            if mode != 'missing-call-id':
                request['callId'] = 'call-9'
            if mode == 'pre-abort':
                request['signal'] = AbortSignal.abort()
            outcome = await service.request(request)
            await record.drain_updates()
            audit = [event for event in session.events if event['type'] in ('approval/asked', 'approval/decided')]
            rows.append({'mode': mode, 'response': response, 'outcome': outcome, 'requests': requests,
                'updates': updates, 'updateBeforePermission': order[0] if order else None,
                'audit': {'types': [event['type'] for event in audit],
                    'correlated': audit[0]['data']['id'] == audit[1]['data']['id'], 'outcome': audit[1]['data']['outcome']}})
        finally:
            detach()
            bridge.sessions.clear()
            bridge.connection.close()
            await bridge.connection.drain()
            await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
