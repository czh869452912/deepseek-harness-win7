"""Versioned pi-ai replay metadata; durable Harness blocks remain authoritative."""
import json

from dsh.llm.llm_service import LlmError


def arguments(raw):
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def empty_usage():
    return dict(input=0, output=0, cacheRead=0, cacheWrite=0, totalTokens=0,
                cost=dict(input=0, output=0, cacheRead=0, cacheWrite=0, total=0))


def replay_state(message):
    response = dict(kind='pi-ai', version=2, **{key: message[key] for key in ('api', 'provider', 'model', 'stopReason')})
    response.update({key: message[key] for key in ('responseModel', 'responseId') if key in message})
    types = dict(text='text', thinking='reasoning', toolCall='tool-call')
    signatures = dict(text=['textSignature'], thinking=['thinkingSignature', 'redacted'], toolCall=['thoughtSignature'])
    return dict(response=response, blocks=[dict(type=types[block['type']], **{key: block[key]
        for key in signatures[block['type']] if key in block}) for block in message['content']])


def invalid(message):
    raise LlmError('invalid pi-ai replay state: ' + message, 'INVALID_REPLAY_STATE')


def read_state(value):
    if not isinstance(value, dict):
        invalid('expected a replay envelope')
    response = value.get('response')
    if not isinstance(response, dict):
        invalid('expected a response object')
    if response.get('kind') != 'pi-ai':
        invalid('unknown state kind')
    if type(response.get('version')) is not int or response['version'] != 2:
        invalid('unsupported version')
    for key in ('api', 'provider', 'model'):
        if not isinstance(response.get(key), str) or not response[key]:
            invalid(key + ' must be a non-empty string')
    if response.get('stopReason') not in ('stop', 'length', 'toolUse', 'error', 'aborted'):
        invalid('unknown stopReason')
    for key in ('responseModel', 'responseId'):
        if key in response and not isinstance(response[key], str):
            invalid(key + ' must be a string')
    blocks = value.get('blocks')
    if not isinstance(blocks, list):
        invalid('blocks must be an array')
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            invalid('block {} must be an object'.format(index))
        if block.get('type') not in ('text', 'reasoning', 'tool-call'):
            invalid('block {} has an unknown type'.format(index))
        for key in ('textSignature', 'thinkingSignature', 'thoughtSignature'):
            if key in block and not isinstance(block[key], str):
                invalid('block {} {} must be a string'.format(index, key))
        if 'redacted' in block and type(block['redacted']) is not bool:
            invalid('block {} redacted must be boolean'.format(index))
    return response, blocks


def native_block(block):
    kind = block['type']
    if kind == 'text':
        return dict(type='text', text=block['text'])
    if kind == 'reasoning':
        return dict(type='thinking', thinking=block['text'])
    if kind == 'tool-call':
        return dict(type='toolCall', id=block['id'], name=block['name'], arguments=arguments(block['arguments']))
    if kind == 'image':
        raise LlmError('pi-ai chat history cannot represent structured assistant image output', 'UNSUPPORTED_CONTENT')
    return None


def foreign_assistant(message):
    source = message.get('source', {})
    if source.get('kind') != 'model':
        source = {}
    content = [native_block(block) for block in message['content']]
    content = [block for block in content if block is not None]
    return dict(role='assistant', content=content, api='dsh-foreign', provider=source.get('provider', 'dsh-foreign'),
        model=source.get('model', 'dsh-foreign'), usage=empty_usage(), timestamp=0,
        stopReason='toolUse' if any(block['type'] == 'toolCall' for block in content) else 'stop')


def replayed_assistant(message, source):
    response, blocks = read_state(source['replayState'])
    for key in ('provider', 'model'):
        if response[key] != source[key]:
            invalid(key + ' does not match assistant source')
    if len(blocks) != len(message['content']):
        invalid('block count does not match assistant content')
    content = []
    signatures = {'text': ['textSignature'], 'reasoning': ['thinkingSignature', 'redacted'], 'tool-call': ['thoughtSignature']}
    for index, (block, replay) in enumerate(zip(message['content'], blocks)):
        if replay['type'] != block['type']:
            invalid('block {} does not match assistant content'.format(index))
        native = native_block(block)
        native.update({key: replay[key] for key in signatures[block['type']] if key in replay})
        content.append(native)
    result = dict(role='assistant', content=content, usage=empty_usage(), timestamp=0)
    result.update({key: response[key] for key in ('api', 'provider', 'model', 'stopReason', 'responseModel', 'responseId') if key in response})
    return result


def to_pi_assistant(message, on_degrade=None):
    source = message.get('source', {})
    if source.get('kind') != 'model' or 'replayState' not in source:
        return foreign_assistant(message)
    try:
        return replayed_assistant(message, source)
    except LlmError as error:
        if error.code != 'INVALID_REPLAY_STATE':
            raise
        if on_degrade is not None:
            on_degrade(str(error))
        return foreign_assistant(message)
