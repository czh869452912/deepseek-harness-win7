"""Receipt-bounded SDK input observation, matching the pinned client API."""
import math

from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.core.session.json import UNDEFINED
from .errors import SdkProtocolError
from .query_input import js_trim


def protocol(message, value):
    raise SdkProtocolError(message + stringify_json(value))


def validated_session_event(value):
    if not isinstance(value, dict) or not isinstance(value.get('type'), str):
        protocol('session.event carried no event envelope: ', value)
    kind, data = value['type'], value.get('data')
    if kind == 'assistant/message':
        message = data.get('message') if isinstance(data, dict) else None
        content = message.get('content') if isinstance(message, dict) else None
        if not isinstance(content, list) or not all(isinstance(block, dict) and isinstance(block.get('type'), str) for block in content):
            protocol('assistant/message event carried malformed content: ', value)
    if kind == 'turn/end':
        if not isinstance(data, dict):
            protocol('turn/end event carried malformed data: ', value)
        reason = data.get('reason')
        if not isinstance(reason, dict) or not isinstance(reason.get('kind'), str):
            protocol('turn/end carried no reason envelope: ', reason)
        if reason['kind'] == 'aborted':
            detail = reason.get('reason')
            if not isinstance(detail, dict) or not isinstance(detail.get('kind'), str):
                protocol('turn/end carried a malformed aborted reason: ', reason)
            if detail['kind'] == 'hook':
                if not isinstance(detail.get('reason'), str):
                    protocol('turn/end carried a malformed hook abort reason: ', reason)
            elif detail['kind'] not in ('user', 'parent', 'disposed', 'legacy'):
                protocol('turn/end carried an unknown abort reason: ', reason)
    return value


def final_response(events):
    for event in reversed(events):
        if event['type'] == 'assistant/message':
            # JS Array.join renders an absent or null text field as empty text.
            return ''.join('' if block.get('text') is None else js_to_string(block['text'])
                           for block in event['data']['message']['content'] if block['type'] == 'text')
    return ''


def command_execution(value):
    if isinstance(value, dict) and isinstance(value.get('commandId'), str) and value['commandId'] and isinstance(value.get('result'), dict):
        result = value['result'];kind = result.get('kind');text = result.get('text', UNDEFINED)
        seq = result.get('sourceEventSeq', UNDEFINED)
        valid_seq = seq is UNDEFINED or (type(seq) in (int, float) and 0 <= seq <= 9007199254740991 and math.isfinite(seq) and int(seq) == seq)
        if kind == 'success' and (text is UNDEFINED or isinstance(text, str)) and valid_seq:
            decoded = dict(kind=kind)
            if text is not UNDEFINED: decoded['text'] = text
            if seq is not UNDEFINED: decoded['sourceEventSeq'] = seq
            return dict(commandId=value['commandId'], result=decoded)
        if kind == 'error' and isinstance(text, str) and js_trim(text):
            return dict(commandId=value['commandId'], result=dict(kind=kind, text=text))
    protocol('session/query returned an invalid command result: ', value)


async def query_input(client, session_id, value):
    content = [dict(type='text', text=value)] if isinstance(value, str) else value
    result = await client.request('session/query', dict(sessionId=session_id, contentBlocks=content))
    if isinstance(result, dict):
        if result.get('kind') == 'prompt' and isinstance(result.get('messageId'), str) and result['messageId']:
            return dict(kind='prompt', messageId=result['messageId'])
        if result.get('kind') == 'command':
            return dict(kind='command', execution=command_execution(result.get('execution')))
    protocol('session/query returned an invalid routing result: ', result)


class RunActivity:
    def __init__(self, session_id, receipt):
        self.session_id, self.receipt = session_id, receipt
        self.received = self.commandDone = False
        self.events, self.notifications = [], []

    def matches_receipt(self, event):
        if not isinstance(event, dict) or not isinstance(event.get('data'), dict):
            return False
        if 'messageId' in self.receipt:
            inserted = event['data'].get('inserted')
            return event.get('type') == 'agent/inbox/spliced' and isinstance(inserted, list) and any(isinstance(message, dict) and message.get('id') == self.receipt['messageId'] for message in inserted)
        return event.get('type') == 'command/run' and event['data'].get('commandId') == self.receipt['commandId']

    def record(self, note, observer=None):
        if note['method'] == 'session.query.completed':
            return False
        params = note['params']
        root = note['method'] == 'session.event' and params['sessionId'] == self.session_id
        if not self.received:
            if not root or not self.matches_receipt(params.get('event')):
                return False
            self.received = True
        event = validated_session_event(params.get('event')) if root else None
        if event is not None and event['type'] == 'command/done' and 'commandId' in self.receipt and isinstance(event.get('data'), dict) and event['data'].get('commandId') == self.receipt['commandId']:
            self.commandDone = True
        self.notifications.append(note)
        if observer is not None: observer(note)
        if event is not None: self.events.append(event)
        return True

    def result(self, completed=None):
        if completed is not None and not self.commandDone:
            raise SdkProtocolError('Command completion is missing matching lifecycle events')
        terminal = next((event for event in reversed(self.events) if event['type'] == 'turn/end'), None)
        return dict(sessionId=self.session_id,
                    finalResponse=completed['finalResponse'] if completed is not None else final_response(self.events),
                    finishReason=completed['finishReason'] if completed is not None else terminal['data']['reason']['kind'] if terminal is not None else None,
                    events=self.events, notifications=self.notifications)


async def run_session(session, value, options=None):
    await session.harness.start()
    client = session.harness.client
    subscription = client.subscribeSessionTree(session.id)
    observer = (options or {}).get('onNotification')
    try:
        response = await query_input(client, session.id, value)
        if response['kind'] == 'command':
            identity = response['execution']['commandId']
            activity = RunActivity(session.id, dict(commandId=identity))
            while True:
                note = await subscription.next();params = note['params']
                if note['method'] == 'session.query.completed' and params['sessionId'] == session.id:
                    if not isinstance(params.get('commandId'), str) or not params['commandId']:
                        raise SdkProtocolError('Invalid session.query.completed command identity')
                    if params['commandId'] != identity: continue
                    if not isinstance(params.get('finalResponse'), str) or not isinstance(params.get('finishReason'), str) or not params['finishReason']:
                        raise SdkProtocolError('Invalid session.query.completed result')
                    while not activity.commandDone:
                        queued = subscription.tryNext()
                        if queued is UNDEFINED: break
                        activity.record(queued, observer)
                    return activity.result(params)
                activity.record(note, observer)
        activity = RunActivity(session.id, dict(messageId=response['messageId']))
        while True:
            note = await subscription.next()
            if not activity.record(note, observer): continue
            if note['method'] == 'session.status' and note['params']['sessionId'] == session.id and note['params']['status'] == 'idle': break
        return activity.result()
    finally:
        subscription.close()
