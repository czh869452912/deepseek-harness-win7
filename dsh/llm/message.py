import copy
import uuid
from typing import Any, Dict


def random_uuid() -> str:
    return str(uuid.uuid4())


def freeze_message(message: Dict[str, Any]) -> Dict[str, Any]:
    from dsh.core.session.json import deep_freeze
    return deep_freeze(copy.deepcopy(message))


freezeMessage = freeze_message


def create_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(input_data)
    result['id'] = random_uuid()
    return freeze_message(result)


createMessage = create_message


def create_user_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(input_data)
    result['role'] = 'user'
    return create_message(result)


createUserMessage = create_user_message


def create_assistant_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    source = {'kind': 'model'}
    if isinstance(input_data.get('source'), dict):
        source.update(input_data['source'])
    result = {'role': 'assistant', 'source': source}
    if 'content' in input_data:
        result['content'] = input_data['content']
    return create_message(result)


createAssistantMessage = create_assistant_message


def create_tool_result_message(input_data: Dict[str, Any]) -> Dict[str, Any]:
    source = {'kind': 'tool'}
    block = {'type': 'tool-result'}
    if 'callId' in input_data:
        source['callId'] = input_data['callId']
        block['toolCallId'] = input_data['callId']
    for name in ('content', 'isError'):
        if name in input_data:
            block[name] = input_data[name]
    return create_user_message({'source': source, 'content': [block]})


createToolResultMessage = create_tool_result_message
