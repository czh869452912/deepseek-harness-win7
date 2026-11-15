"""Project immutable Session tool history for the selected model capability."""


def _without_developer(messages):
    retained = [message for message in messages if message['role'] != 'developer']
    return messages if len(retained) == len(messages) else retained


def _rebase_addition_only(history, messages):
    available = {tool['name']: tool for tool in history['tools']}
    baseline, retained_from = history['tools'], 0
    for index, update in enumerate(history['updates']):
        additions = {tool['name']: tool for tool in update['additions']}
        reset = not available and bool(additions)
        for block in messages[update['messageId']]:
            if block['type'] == 'tool-addition':
                tool = {key: value for key, value in additions[block['toolName']].items() if key != 'deferLoading'}
                available[tool['name']] = tool
            elif block['type'] == 'tool-removal':
                reset = True
                available.pop(block['toolName'], None)
        if reset:
            baseline, retained_from = list(available.values()), index + 1
    return history if retained_from == 0 else dict(tools=baseline, updates=history['updates'][retained_from:])


def project_tool_updates(messages, tools=None, tool_update=None, history=None):
    if tool_update is None:
        immediate = tools
        if tools is not None and any(tool.get('deferLoading') is True for tool in tools):
            immediate = [{key: value for key, value in tool.items() if key != 'deferLoading'} for tool in tools]
        return dict(messages=_without_developer(messages), tools=immediate)
    if history is None:
        return dict(messages=_without_developer(messages), tools=tools)
    updates = {message['id']: message['content'] for message in messages if message['role'] == 'developer'}
    if any(update['messageId'] not in updates for update in history['updates']):
        return dict(messages=_without_developer(messages), tools=tools)
    projected = _rebase_addition_only(history, updates) if tool_update == 'addition-only' else history
    declarations = {tool['name']: tool for tool in projected['tools']}
    for update in projected['updates']:
        for tool in update['additions']:
            if tool['name'] not in declarations:
                declarations[tool['name']] = dict(tool, deferLoading=True)
    update_ids = {update['messageId'] for update in history['updates']}
    retained_ids = {update['messageId'] for update in projected['updates']}
    offered = {tool['name'] for tool in projected['tools'] if not tool.get('deferLoading')}
    result = []
    for message in messages:
        if message['role'] != 'developer':
            result.append(message)
            continue
        if message['id'] not in update_ids:
            continue
        content = []
        for block in message['content']:
            kind = block['type']
            if kind == 'tool-addition':
                name = block['toolName']
                if message['id'] not in retained_ids or name not in declarations or name in offered:
                    continue
                offered.add(name)
            elif kind == 'tool-removal':
                name = block['toolName']
                if tool_update != 'in-history' or name not in offered:
                    continue
                offered.remove(name)
            content.append(block)
        if content:
            result.append(message if len(content) == len(message['content']) else dict(message, content=content))
    unchanged = len(result) == len(messages) and all(left is right for left, right in zip(result, messages))
    return dict(messages=messages if unchanged else result, tools=list(declarations.values()))


projectToolUpdates = project_tool_updates
