"""Minimal Messages thinking signatures alongside provider-neutral durable blocks."""
from dsh.cordis.utils import _UNDEFINED
from dsh.llm.llm_service import LlmError


def object_value(value, code='MALFORMED_RESPONSE'):
    if not isinstance(value,dict): raise LlmError('DeepSeek Messages expected a JSON object',code)
    return value


def replayState(model, blocks):
    return dict(response=dict(kind='deepseek-messages',version=1,model=model),blocks=blocks)


def readReplay(message, model, onDegrade=None):
    try: return _validate(message,model)
    except LlmError as error:
        if error.code != 'INVALID_REPLAY_STATE': raise
        if onDegrade is not None: onDegrade(error.message)
        return None


def _validate(message, model):
    source = message['source']
    if source['kind'] != 'model' or 'replayState' not in source: return None
    def fail(detail): raise LlmError('DeepSeek Messages replay: '+detail,'INVALID_REPLAY_STATE')
    envelope = object_value(source['replayState'],'INVALID_REPLAY_STATE')
    response = object_value(envelope.get('response'),'INVALID_REPLAY_STATE')
    if response.get('kind') != 'deepseek-messages' or type(response.get('version')) not in (int,float) or response['version'] != 1:
        fail('unsupported kind or version')
    if response.get('model',_UNDEFINED) != source.get('model',_UNDEFINED): fail('model does not match assistant source model')
    blocks = envelope.get('blocks')
    if not isinstance(blocks,list) or len(blocks) != len(message['content']): fail('block count mismatch')
    result = []
    for index,value in enumerate(blocks):
        block = object_value(value,'INVALID_REPLAY_STATE')
        kind = block.get('type')
        if kind != message['content'][index].get('type') or kind not in ('text','reasoning','tool-call'): fail('block type mismatch')
        if 'signature' in block and (kind != 'reasoning' or not isinstance(block['signature'],str)): fail('invalid signature')
        row = dict(type=kind)
        if isinstance(block.get('signature'),str): row['signature'] = block['signature']
        result.append(row)
    return result if response.get('model') == model else None
