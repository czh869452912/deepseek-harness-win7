UNDEFINED = object()


def scalar_equals(first, second):
    if first is UNDEFINED or second is UNDEFINED:
        return first is second
    if isinstance(first, bool) or isinstance(second, bool):
        return isinstance(first, bool) and isinstance(second, bool) and first == second
    if isinstance(first, (int, float)) and isinstance(second, (int, float)):
        return first == second
    if isinstance(first, str) or isinstance(second, str):
        return isinstance(first, str) and isinstance(second, str) and first == second
    return first is second


def call_config_equals(first, second):
    for field in ('provider', 'model', 'reasoningEffort', 'temperature', 'maxTokens'):
        if not scalar_equals(first.get(field, UNDEFINED), second.get(field, UNDEFINED)):
            return False
    first_stop = first.get('stop', UNDEFINED)
    second_stop = second.get('stop', UNDEFINED)
    if first_stop is UNDEFINED or second_stop is UNDEFINED:
        return first_stop is second_stop
    return len(first_stop) == len(second_stop) and all(
        scalar_equals(value, second_stop[index]) for index, value in enumerate(first_stop))
