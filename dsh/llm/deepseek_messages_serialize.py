"""Messages requests from provider-neutral projected history, without durable edits."""
import base64
import copy

from dsh.cordis.utils import js_to_string,_js_truthy as js_truthy
from dsh.llm.deepseek_messages_replay import readReplay
from dsh.llm.image_content import handle
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_json import loads


def _unsupported(kind): raise LlmError('DeepSeek Messages cannot represent '+kind,'UNSUPPORTED_CONTENT')


def _tool_input(raw):
    try: value = loads(raw)
    except Exception: return {}
    return value if isinstance(value,dict) else {}


def _assistant(message, model, on_degrade):
    replay = readReplay(message,model,on_degrade)
    result = []
    for index,block in enumerate(message['content']):
        kind = block['type']
        if kind == 'text':
            if block['text']: result.append(dict(type='text',text=block['text']))
        elif kind == 'reasoning':
            row = dict(type='thinking',thinking=block['text'])
            if replay is not None and 'signature' in replay[index]: row['signature'] = replay[index]['signature']
            result.append(row)
        elif kind == 'tool-call': result.append(dict(type='tool_use',id=block['id'],name=block['name'],input=_tool_input(block['arguments'])))
        else: _unsupported('assistant content '+kind)
    return result


def serialize(options, connection, history, images, access, onReplayDegrade=None, fileIds=None):
    model = next((entry for entry in connection['models'] if entry['id'] == options['model']),{})
    in_history = model.get('systemPromptUpdate') == 'in-history'
    def inputs(blocks):
        result = []
        for block in blocks:
            kind = block['type']
            if kind == 'text':
                if block['text']: result.append(dict(type='text',text=block['text']))
                continue
            if kind in ('reasoning','tool-call'): continue
            if kind != 'image': _unsupported('user/tool-result content '+kind)
            ref = block['attachment'];version = images.get(ref['attachmentId'])
            if version is None: raise LlmError('DeepSeek Messages request image is missing','INVALID_REQUEST')
            file_id = None if fileIds is None else fileIds.get(ref['attachmentId'])
            if fileIds is not None and file_id is None: raise LlmError('DeepSeek Messages request file id is missing','INVALID_REQUEST')
            location = access(ref)
            result.append(dict(type='text',text=handle(ref,version,None if location is None else location['readonlyPath'])))
            source = dict(type='base64',media_type=version['mediaType'],data=base64.b64encode(version['data']).decode('ascii')) if file_id is None else dict(type='file',file_id=file_id)
            result.append(dict(type='image',source=source))
        return result
    messages,updates,history_system = [],[],None
    def flush():
        if not updates: return
        if not messages or messages[-1]['role'] != 'user': _unsupported('system update without a preceding user or tool-result turn')
        messages.extend(updates);updates.clear()
    for message in history:
        role = message['role']
        if role == 'developer':
            content = []
            for block in message['content']:
                kind = block['type']
                if kind == 'text':
                    if block['text']: content.append(dict(type='text',text=block['text']))
                elif kind in ('tool-addition','tool-removal'):
                    content.append(dict(type='tool_addition' if kind == 'tool-addition' else 'tool_removal',tool=dict(type='tool_reference',name=block['toolName'])))
                else: _unsupported('developer content '+kind)
            if content: updates.append(dict(role='system',content=content))
            continue
        if any(block['type'] in ('tool-addition','tool-removal') for block in message['content']): _unsupported('tool-change blocks outside developer messages')
        if role == 'system':
            if any(block['type'] != 'text' for block in message['content']): _unsupported('non-text system message')
            text = ''.join(block['text'] for block in message['content'])
            if in_history and messages:
                if not text: _unsupported('empty in-history system update')
                updates.append(dict(role='system',content=[dict(type='text',text=text)]))
            else: history_system = text
            continue
        if role == 'assistant': content = _assistant(message,options['model'],onReplayDegrade)
        elif role == 'tool':
            row = dict(type='tool_result',tool_use_id=message['toolCallId'],content=inputs(message['content']))
            if 'isError' in message: row['is_error'] = message['isError']
            content = [row]
        else: content = inputs(message['content'])
        if role in ('user','assistant') and not content: continue
        if role == 'assistant': flush()
        wire_role = 'user' if role == 'tool' else role
        if messages and messages[-1]['role'] == wire_role: messages[-1]['content'].extend(content)
        else: messages.append(dict(role=wire_role,content=content))
    flush()
    pending = set()
    for message in messages:
        if message['role'] == 'assistant':
            calls = [block for block in message['content'] if block['type'] == 'tool_use']
            pending = {block['id'] for block in calls}
            if len(pending) != len(calls): raise LlmError('DeepSeek Messages duplicate tool call id','INVALID_REQUEST')
        elif message['role'] == 'user':
            results = [block for block in message['content'] if block['type'] == 'tool_result']
            for result in results:
                if result['tool_use_id'] not in pending: raise LlmError('DeepSeek Messages tool result has no matching call','INVALID_REQUEST')
                pending.remove(result['tool_use_id'])
            if pending: raise LlmError('DeepSeek Messages tool calls need immediate results','INVALID_REQUEST')
            message['content'] = results+[block for block in message['content'] if block['type'] != 'tool_result']
    if pending: raise LlmError('DeepSeek Messages history ends with unresolved tools','INVALID_REQUEST')
    effort = options.get('reasoningEffort')
    if effort is None: effort = connection['defaults'].get('reasoningEffort')
    if effort is None: effort = 'off' if connection['defaults'].get('thinking') == 'disabled' else 'high'
    if effort not in ('off','low','high','max') or connection['defaults'].get('thinking') == 'disabled' and effort != 'off':
        raise LlmError('DeepSeek Messages does not support reasoning effort '+js_to_string(effort),'UNSUPPORTED_REASONING_EFFORT')
    system = '\n\n'.join(value for value in (options.get('system'),history_system) if js_truthy(value))
    cap = options.get('maxTokens')
    if cap is None: cap = model.get('maxTokens')
    if cap is None: cap = connection['maxTokens']
    result = dict(model=options['model'],stream=True,messages=messages,max_tokens=cap,thinking=dict(type='disabled' if effort == 'off' else 'enabled'))
    if effort != 'off': result['output_config'] = dict(effort=effort)
    if system: result['system'] = system
    for source,target in [('temperature','temperature'),('stop','stop_sequences')]:
        if source in options: result[target] = copy.deepcopy(options[source])
    if 'tools' in options:
        result['tools'] = [dict(name=tool['name'],description=tool['description'],input_schema=copy.deepcopy(tool['parameters']),
                               **(dict(defer_loading=True) if tool.get('deferLoading') is True else {})) for tool in options['tools']]
    return result
