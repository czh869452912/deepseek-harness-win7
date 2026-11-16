"""Contributed request fields and their commit after HTTP acceptance."""
from types import SimpleNamespace

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.llm.error import error_chain
from dsh.llm.llm_service import LlmError


def _get(value,key):
    return value[key] if isinstance(value,dict) else getattr(value,key)


async def prepareRequestExtensions(body,options,prepare,onOmitted,onUnaccepted):
    request=dict(body=body);request.update(options)
    try:
        extensions=await await_callback_result(prepare(request))
    except Exception as error:
        failure=LlmError('DeepSeek request extension preparation failed: '+error_chain(error),'REQUEST_EXTENSION')
        failure.cause=error
        raise failure from error
    contributions=_get(extensions,'fields')
    fields=_js_own_enumerable_keys(contributions)
    for field in fields:
        if field in body:
            raise LlmError('DeepSeek request extension field '+stringify_json(field)+' collides with the base request','REQUEST_EXTENSION')
    try:
        payload=stringify_json(dict(body,**contributions))
    except Exception as error:
        # A failure in the base request itself must precede omission reporting.
        base=stringify_json(body)
        onOmitted(fields,error)
        async def noop():pass
        return SimpleNamespace(payload=base,accept=noop)
    async def accept():
        try:
            await await_callback_result(_get(extensions,'accept')())
        except Exception as error:
            onUnaccepted(error)
    return SimpleNamespace(payload=payload,accept=accept)
