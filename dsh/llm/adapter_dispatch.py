import inspect


def invoke_adapter_stream(method, request):
    parameters = inspect.signature(method).parameters
    if 'request' in parameters and 'messages' not in parameters:
        return method(request=request)
    if 'options' in parameters and 'messages' not in parameters:
        return method(options=request)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return method(**request)
    selected = {key: value for key, value in request.items() if key in parameters}
    if 'request' in parameters:
        selected['request'] = request
    if not selected and len(parameters) == 1:
        return method(request)
    return method(**selected)
