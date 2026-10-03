import json

from dsh.acp.content import assistant_block_to_acp
from dsh.acp.model_control import resolved


async def assistant_updates(ctx, session, event):
    data = event['data']
    message = data['message']
    updates = []
    for block in message['content']:
        if block['type'] == 'reasoning':
            if block['text']:
                updates.append({'sessionUpdate': 'agent_thought_chunk', 'messageId': message['id'],
                                'content': {'type': 'text', 'text': block['text']}})
            continue
        content = await assistant_block_to_acp(ctx, block)
        if content is not None:
            updates.append({'sessionUpdate': 'agent_message_chunk', 'messageId': message['id'], 'content': content})
    if data.get('usage') is not None:
        context = session.request_context()
        meter = ctx.get('tokenMeter')
        capacity = context.get('contextWindow') if isinstance(context, dict) else getattr(context, 'contextWindow', None)
        if capacity is not None and meter is not None:
            measured = await resolved(meter.measure(session))
            used = measured['totalTokens'] if isinstance(measured, dict) else measured.totalTokens
            updates.append({'sessionUpdate': 'usage_update', 'used': used, 'size': capacity})
    return updates


def invalid_json_constant(value):
    raise ValueError(value)


def tool_call_update(event):
    data = event['data']
    try:
        arguments = json.loads(data['arguments'], parse_constant=invalid_json_constant)
    except (ValueError, TypeError):
        arguments = data['arguments']
    return {'sessionUpdate': 'tool_call', 'toolCallId': data['callId'], 'title': data['name'],
            'kind': 'other', 'status': 'in_progress', 'rawInput': arguments}


async def tool_result_update(ctx, event):
    result = event['data']['message']['content'][0]
    content = []
    for block in result['content']:
        converted = await assistant_block_to_acp(ctx, block)
        if converted is not None:
            content.append({'type': 'content', 'content': converted})
    return {'sessionUpdate': 'tool_call_update', 'toolCallId': result['toolCallId'],
            'status': 'failed' if result.get('isError') is True else 'completed', 'content': content}
