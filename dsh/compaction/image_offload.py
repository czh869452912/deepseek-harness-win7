"""Pure durable image interpretation; recovery listeners belong to the plugin."""
from dsh.core.session.current import safe
from dsh.core.session.json import deep_freeze
from dsh.session.format_v2_to_v3.payload import display


def offloadMessageImages(message, indexes):
    image_index, selected, content = 0, 0, None
    for index, block in enumerate(message['content']):
        projected = block
        if block.get('type') == 'image':
            if selected < len(indexes) and image_index == indexes[selected]:
                if block.get('offloaded') is True:
                    raise ValueError('image/offload: image index %s is already offloaded' % image_index)
                projected = dict(block, offloaded=True)
                selected += 1
            image_index += 1
        if projected is not block and content is None:
            content = list(message['content'][:index])
        if content is not None:
            content.append(projected)
    if selected != len(indexes):
        raise ValueError('image/offload: image index %s does not exist' % display(indexes[selected]))
    return deep_freeze(dict(message, content=message['content'] if content is None else content))


def _project(event, context):
    data = event['data']
    if not isinstance(data, dict) or set(data) != {'targets'} or not isinstance(data['targets'], list) or not data['targets']:
        raise ValueError('image/offload: data must contain a nonempty targets array')
    messages, nodes = {}, set(context.nodes)
    for target in data['targets']:
        if (not isinstance(target, dict) or set(target) != {'seq', 'imageIndexes'}
                or not safe(target['seq'], True, True) or not isinstance(target['imageIndexes'], list) or not target['imageIndexes']):
            raise ValueError('image/offload: each target must contain a seq and nonempty imageIndexes')
        seq = target['seq']
        if seq in messages:
            raise ValueError('image/offload: duplicate target seq %s' % display(seq))
        if seq not in nodes:
            raise ValueError('image/offload: target seq %s is not a current surface node' % display(seq))
        index = seq-context.baseSeq
        source = context.events[int(index)] if 0 <= index < len(context.events) else None
        if source is None or source['type'] not in ('user/message', 'tool/result'):
            raise ValueError('image/offload: target seq %s must be user/message or tool/result' % display(seq))
        previous = -1
        for index in target['imageIndexes']:
            if not safe(index, True, True) or index <= previous:
                raise ValueError('image/offload: imageIndexes must be strictly increasing non-negative safe integers')
            previous = index
        message = context.messages.get(seq)
        if message is None:
            message = source['data'] if source['type'] == 'user/message' else source['data']['message']
        messages[seq] = offloadMessageImages(message, target['imageIndexes'])
    return messages


imageOffloadProjection = dict(type='image/offload', project=_project)
