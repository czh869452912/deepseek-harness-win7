"""Native developer tool-change and deferred-schema field admission."""
from dsh.core.session.json import UNDEFINED
from dsh.session.format import SessionFormatError, sessionFormatCount


def _tool_change(block, developer):
    if not isinstance(block, dict) or block.get('type') not in ('tool-addition', 'tool-removal'):
        return
    kind = block['type']
    if not developer:
        raise SessionFormatError('format v4 ' + kind + ' requires developer role')
    if not isinstance(block.get('toolName'), str) or not block['toolName']:
        raise SessionFormatError('format v4 ' + kind + ' requires a nonempty toolName')
    if kind == 'tool-addition' and 'tool' in block:
        raise SessionFormatError('format v4 tool-addition must omit inline tool definitions')


def _content(value, developer=False):
    if isinstance(value, list):
        for block in value:
            _tool_change(block, developer)


def _ordinary_message(value):
    if not isinstance(value, dict):
        return
    if value.get('role') == 'developer':
        raise SessionFormatError('format v4 developer/message and developer role must occur together')
    _content(value.get('content'))


def assertV4DeveloperData(event):
    data = event.get('data')
    kind = event.get('type')
    if not isinstance(data, dict):
        if kind == 'developer/message':
            raise SessionFormatError('format v4 developer/message data must be an object')
        return
    if kind == 'developer/message':
        message = data.get('message')
        if not isinstance(message, dict) or message.get('role') != 'developer':
            raise SessionFormatError('format v4 developer/message requires turn, step, and a developer message')
        for field in ('turn', 'step'):
            if sessionFormatCount(data.get(field, UNDEFINED), 'developer/message ' + field) == 0:
                raise SessionFormatError('developer/message ' + field + ' must be positive')
        _content(message.get('content'), True)
        source = message.get('source')
        if (not isinstance(message.get('id'), str) or not message['id']
                or not isinstance(message.get('content'), list) or not isinstance(source, dict)
                or not isinstance(source.get('kind'), str) or not source['kind'] or source['kind'] == 'plugin'):
            raise SessionFormatError('format v4 developer message requires id, role, content, and a producer-owned source')
        additions = any(isinstance(block, dict) and block.get('type') == 'tool-addition' for block in message['content'])
        if additions:
            sessionFormatCount(data.get('headerSeq', UNDEFINED), 'developer/message headerSeq')
        elif 'headerSeq' in data:
            raise SessionFormatError('format v4 developer/message must omit headerSeq without tool additions')
    elif kind == 'user/message':
        _ordinary_message(data)
    elif kind in ('system/message', 'assistant/message', 'tool/result'):
        _ordinary_message(data.get('message'))
    elif kind in ('agent/inbox/spliced', 'session/title-llm-request'):
        messages = data.get('inserted' if kind == 'agent/inbox/spliced' else 'messages')
        if isinstance(messages, list):
            for message in messages:
                _ordinary_message(message)
    if kind == 'compaction/summary':
        _content(data.get('summary'))
        _content(data.get('rawOutput'))
    if kind in ('assistant/message', 'assistant/attempt') and isinstance(data.get('stream'), list):
        for entry in data['stream']:
            if not isinstance(entry, dict) or entry.get('type') != 'chunk':
                continue
            chunk = entry.get('chunk')
            if not isinstance(chunk, dict):
                continue
            if chunk.get('type') == 'block-end':
                _tool_change(chunk.get('block'), False)
            if chunk.get('type') == 'block-start' and chunk.get('blockType') in ('tool-addition', 'tool-removal'):
                raise SessionFormatError('format v4 tool-change blocks require developer role')
    if kind == 'request/header' and isinstance(data.get('header'), dict):
        tools = data['header'].get('tools')
        if isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict) and 'deferLoading' in tool and tool['deferLoading'] is not True:
                    raise SessionFormatError('format v4 tool deferLoading must be true when present')
