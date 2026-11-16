"""Current field registry: isolate preparation failures and warn once per field."""
import asyncio
import copy

from dsh.core.session.json import deep_freeze
from dsh.cordis.json_text import stringify_json
from dsh.cordis.errors import AggregateError
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.llm.deepseek_api_extensions import (
    DeepSeekLlmApiExtensionRegistry, PreparedDeepSeekLlmApiExtensions,
    _throw_if_aborted, _resolve_prepare, _resolve_result, _maybe_awaited, abortable,
    _settle_callback,
)


class _Commit:
    def __init__(self,callbacks):
        async def settle():
            outcomes=await asyncio.gather(*(_settle_callback(callback) for callback in callbacks),return_exceptions=True)
            errors=[outcome for outcome in outcomes if isinstance(outcome,BaseException)]
            if len(errors)==1:raise errors[0]
            if errors:raise AggregateError(errors,'DeepSeek LLM API extension acceptance failed')
        self.task=asyncio.ensure_future(settle())
        self.task.add_done_callback(lambda done:None if done.cancelled() else done.exception())

    def __await__(self):
        return asyncio.shield(self.task).__await__()


class _Prepared(PreparedDeepSeekLlmApiExtensions):
    def accept(self):
        if self._acceptance is None:self._acceptance=_Commit(self._callbacks)
        return self._acceptance


def _clone(value):
    # The public extension value is a plain JSON tree. Detect clone failures
    # before freezing, including functions and cycles that structuredClone /
    # Source's recursive freeze cannot admit as prepared JSON contributions.
    pending=[(value,False)];active=set()
    while pending:
        current,leaving=pending.pop()
        if isinstance(current,(dict,list)):
            identity=id(current)
            if leaving:
                active.remove(identity);continue
            if identity in active:raise ValueError('Maximum call stack size exceeded')
            active.add(identity);pending.append((current,True))
            pending.extend((item,False) for item in (current.values() if isinstance(current,dict) else current))
        elif current is not None and not isinstance(current,(bool,int,float,str)):
            raise ValueError('Value could not be cloned.')
    return deep_freeze(copy.deepcopy(value))


class CurrentDeepSeekLlmApiExtensions(DeepSeekLlmApiExtensionRegistry):
    def __init__(self,ctx=None):
        super().__init__(ctx)
        self.warnedFields=set()

    def register(self,field,provider):
        if not isinstance(field,str) or not field or field.strip(JS_SPACE)!=field:
            raise ValueError('deepseek-llm-api-extensions: field must be a non-blank trimmed string')
        def setup():
            if field in self._providers:
                raise ValueError('deepseek-llm-api-extensions: field '+stringify_json(field)+' is already registered')
            self._providers[field]=provider
            return lambda:self._providers.pop(field,None)
        return self.ctx.effect(setup,label='deepseekLlmApiExtensions.register('+stringify_json(field)+')')

    async def prepare(self,request):
        signal=request['signal'];_throw_if_aborted(signal)
        entries=list(self._providers.items())
        async def prepare_one(field,provider):
            try:
                result=await _maybe_awaited(_resolve_prepare(provider)(request))
                if result is None:return None
                value,accept=_resolve_result(result)
                return field,_clone(value),accept
            except Exception as error:
                if not signal.aborted and field not in self.warnedFields:
                    self.warnedFields.add(field)
                    self.ctx.logger.warn('deepseek-llm-api-extensions: omitting field '+stringify_json(field)
                        +' from this request because its preparation failed: %o',error)
                return None
        prepared=await abortable(asyncio.gather(*(prepare_one(field,provider) for field,provider in entries)),signal)
        fields,callbacks={},[]
        for item in prepared:
            if item is None:continue
            field,value,accept=item;fields[field]=value
            if accept is not None:callbacks.append(accept)
        return _Prepared(deep_freeze(fields),callbacks)
