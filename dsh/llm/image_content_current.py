"""Durable image marks and exact represented-byte request admission."""
import math

from dsh.llm.image_content import handle, omitted


def image_blocks(messages):
    for message in messages:
        for block in message['content']:
            if block['type'] == 'image':
                yield block


def access_path(access):
    return None if access is None else access['readonlyPath']


def offloadedImageText(ref, access=None):
    return omitted(ref, access_path(access))


def requestImageHandleText(ref, version, access=None):
    return handle(ref, version, access_path(access))


def projectOffloadedImages(messages, placeholder):
    result = []
    for message in messages:
        changed = False
        content = []
        for block in message['content']:
            if block['type'] == 'image' and block.get('offloaded') is True:
                content.append(dict(type='text', text=placeholder(block['attachment'])))
                changed = True
            else:
                content.append(block)
        result.append(dict(message, content=content) if changed else message)
    return result


def requiredImageOffload(messages, budget, versionBytes):
    lengths = []
    for block in image_blocks(messages):
        if block.get('offloaded') is True:
            continue
        size = versionBytes(block)
        lengths.append(math.ceil(size / 3) * 4 if budget['representation'] == 'base64' else size)
    excess_count = max(0, len(lengths)-budget['maxImages']) if 'maxImages' in budget else 0
    excess_bytes = max(0, sum(lengths)-budget['maxBytes']) if 'maxBytes' in budget else 0
    if not excess_count and not excess_bytes:
        return 0
    count_quantum, byte_quantum = budget.get('countQuantum', 1), budget.get('byteQuantum', 1)
    remove_count = math.ceil(excess_count/count_quantum)*count_quantum
    remove_bytes = math.ceil(excess_bytes/byte_quantum)*byte_quantum
    count, removed = 0, 0
    for size in lengths:
        met = not remove_bytes or (removed >= remove_bytes if byte_quantum == 1 else removed > remove_bytes)
        if count >= remove_count and met:
            break
        removed += size
        count += 1
    return count
