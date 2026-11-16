"""Modern MCP result decoding for the harness's SDK-default request surface."""
from dsh.mcp.current import RESOURCE_SCHEMAS
from dsh.mcp.negotiation_current import SdkError
from dsh.mcp.schemas import parse, SchemaError


def decode_modern_result(method, raw):
    def invalid(detail, **data):
        return dict(kind='invalid', error=SdkError('INVALID_RESULT', 'Invalid result for '+method+': '+detail, dict(method=method, **data)))
    if not isinstance(raw, dict):
        return invalid('not an object')
    if 'resultType' not in raw:
        return invalid('missing required resultType — servers implementing protocol revision 2026-07-28 MUST include it (the absent-means-complete bridge applies only to earlier-revision servers)', violation='missing-resultType')
    kind = raw['resultType']
    if not isinstance(kind, str):
        return invalid('non-string resultType', resultType=kind)
    if kind == 'input_required':
        requests = raw.get('inputRequests')
        requests = requests if isinstance(requests, dict) else {}
        state = raw.get('requestState')
        if not requests and not isinstance(state, str):
            return invalid('input_required carries neither inputRequests nor requestState (every input_required result must include at least one of the two)', violation='input-required-missing-both')
        result = dict(kind='input_required', inputRequests=requests)
        if isinstance(state, str):
            result['requestState'] = state
        if '_meta' in raw:
            try:
                result['_meta'] = parse('ModernResultMeta', raw['_meta'], RESOURCE_SCHEMAS)
            except SchemaError:
                pass
        return result
    if kind != 'complete':
        return dict(kind='invalid', error=SdkError('UNSUPPORTED_RESULT_TYPE', "Unsupported result type '"+kind+"' for "+method, dict(resultType=kind, method=method)))
    schema = 'ModernWire:'+method
    if schema in RESOURCE_SCHEMAS['schemas']:
        try:
            parse(schema, raw, RESOURCE_SCHEMAS)
        except SchemaError as error:
            return invalid(str(error))
    return dict(kind='complete', result={key:value for key,value in raw.items() if key!='resultType'})


def project_modern_result(method, raw):
    decoded = decode_modern_result(method, raw)
    if decoded['kind'] == 'invalid':
        raise decoded['error']
    if decoded['kind'] == 'input_required':
        raise SdkError('UNSUPPORTED_RESULT_TYPE', "Unsupported result type 'input_required' for "+method+": multi-round-trip auto-fulfilment is not enabled on this instance — pass allowInputRequired: true to handle it manually, or enable inputRequired.autoFulfill", dict(resultType='input_required', method=method))
    schema = 'ModernDispatch:'+method
    try:
        return parse(schema, decoded['result'], RESOURCE_SCHEMAS) if schema in RESOURCE_SCHEMAS['schemas'] else decoded['result']
    except SchemaError as error:
        raise SdkError('INVALID_RESULT', 'Invalid result for '+method+': '+str(error))
