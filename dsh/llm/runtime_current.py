"""rc.3 prepared-call system prompt capabilities, without moving the active pin."""
from dsh.llm.llm_service import LLMService, LlmRuntime, LlmError
from dsh.llm.model_info import normalize_model_info
from dsh.llm.file_content_current import file_handle_text, project_files_to_text
from dsh.core.session.json import FrozenDict, deep_freeze


class CurrentLLMService(LLMService):
    registerAdapter = LLMService.register_adapter
    resolveModelInfo = LLMService.resolve_model_info
    listModels = LLMService.list_models
    @staticmethod
    def _normalize_model_info(provider, identifier, model, error_type):
        return normalize_model_info(provider, identifier, model, error_type, system_prompt_update=True)

    def _call_capabilities(self, model_info):
        return {key: model_info[key] for key in ('systemPromptUpdate', 'toolUpdate') if key in model_info}

    def _file_read_path(self, ref):
        try:
            attachments = self.ctx.get('attachments') if self.ctx is not None else None
            host_path = attachments.fileHostPath(ref) if attachments is not None else None
        except Exception:
            return None  # Invalid durable references degrade only this occurrence.
        if host_path is None:
            return None
        fs = self.ctx.get('fs') if self.ctx is not None else None
        # Mapping failures are provider failures, not invalid attachment refs.
        return fs.processPathFromHostPath(host_path) if fs is not None else None

    def fileRequestText(self, ref):
        return file_handle_text(ref, self._file_read_path(ref))

    def _project_adapter_request(self, options, model_info):
        messages = project_files_to_text(options['messages'], self._file_read_path)
        request = options
        if messages is not options['messages']:
            request = dict(options, messages=messages)
            if isinstance(options, FrozenDict):
                request = deep_freeze(request)
        request = super()._project_adapter_request(request, model_info)
        from dsh.llm.tool_updates import project_tool_updates
        projected = project_tool_updates(request['messages'], request.get('tools'),
                                         model_info.get('toolUpdate'), request.get('toolHistory'))
        if projected['messages'] is not request['messages'] or projected['tools'] is not request.get('tools'):
            result = dict(request, messages=projected['messages'])
            if projected['tools'] is not None:
                result['tools'] = projected['tools']
            request = deep_freeze(result) if isinstance(options, FrozenDict) else result
        return request

    async def stream(self, options):
        """Direct calls share the final boundary with prepared Agent calls.

        Resolution stays inside the waterfall so a short-circuiting middleware
        never needs an adapter, filesystem, or attachment provider.
        """
        from dsh.cordis.awaiting import await_callback_result
        from dsh.llm.call_config import call_config_equals
        from dsh.llm.stream_bridge import iter_chunks

        async def adapter_stream(*_arguments):
            try:
                provider = options['provider']
                registration = self._adapters.get(provider)
                if registration is None:
                    raise LlmError('no adapter registered for provider "{}"'.format(provider), 'NO_ADAPTER')
                adapter = registration['adapter']
                prepare = getattr(adapter, 'prepareCall', None) or getattr(adapter, 'prepare_call', None)
                if prepare is not None:
                    prepared = await await_callback_result(prepare(provider, options['model'], options.get('signal')))
                    info, dispatch = prepared['model'], prepared['stream']
                else:
                    info = await self.resolve_model_info(provider, options['model'], options.get('signal'))
                    dispatch = adapter.stream
                info = self._normalize_model_info(provider, options['model'], info, LlmError)
                config = {key: options[key] for key in ('provider', 'model', 'maxTokens', 'reasoningEffort') if key in options}
                resolved = self._resolve_call_with_info(config, info)
                request = options
                if not call_config_equals(options, resolved):
                    request = dict(options, **resolved)
                    if isinstance(options, FrozenDict):
                        request = deep_freeze(request)
                request = self._project_adapter_request(request, info)
                messages = []
                changed = False
                for message in request['messages']:
                    source = message.get('source', {})
                    if (message.get('role') == 'assistant' and source.get('kind') == 'model'
                            and 'replayState' in source and self._adapters.get(source.get('provider'), {}).get('adapter') is not adapter):
                        message = deep_freeze(dict(message, source={key: source[key] for key in ('kind', 'provider', 'model')}))
                        changed = True
                    messages.append(message)
                if changed:
                    request = dict(request, messages=messages)
                    if isinstance(options, FrozenDict):
                        request = deep_freeze(request)
                raw = dispatch(request)
                reader = raw.__aiter__() if hasattr(raw, '__aiter__') else iter_chunks(raw)
            except Exception as error:
                yield self._adapter_failure_chunk(error, options.get('signal'))
                return
            completed = False
            try:
                while True:
                    try:
                        chunk = await reader.__anext__()
                    except StopAsyncIteration:
                        completed = True
                        return
                    except Exception as error:
                        completed = True
                        yield self._adapter_failure_chunk(error, options.get('signal'))
                        return
                    yield chunk
            finally:
                if not completed:
                    close = getattr(reader, 'aclose', None)
                    if close is not None:
                        await close()

        # Cordis accepts a synchronous continuation returning the iterable.
        stream = await self.ctx.waterfall('llm/stream', options, lambda *_: adapter_stream()) if self.ctx is not None else adapter_stream()
        reader = iter_chunks(stream)
        try:
            async for chunk in reader:
                yield chunk
        finally:
            await reader.aclose()


class CurrentLlmRuntime(LlmRuntime):
    _service_class = CurrentLLMService
