"""Snapshot-bound native pi-ai adapter; implemented protocols are explicit."""
import asyncio
import copy
import logging

from dsh.llm.attribution import attribution_headers
from dsh.llm.image_content import images
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_auth import resolve_api_key
from dsh.llm.pi_config import resolve_profiles
from dsh.llm.pi_context import to_pi_context, to_pi_context_with_images
from dsh.llm.pi_model import model_info, resolve_reasoning_level
from dsh.llm.pi_stream import to_stream_chunks
from dsh.llm.stream_bridge import OwnedStream, iter_chunks

NATIVE_PROTOCOLS = ('openai-completions',)


def native_profiles(config):
    profiles = resolve_profiles(config.get('providers'))
    for profile in profiles.values():
        for model in profile['models']:
            if model['api'] not in NATIVE_PROTOCOLS:
                raise ValueError('llm-pi-ai: native Python protocol "{}" is not implemented; route "{}" cannot be served'.format(
                    model['api'], profile['provider']))
    return profiles


class PiAiAdapter:
    def __init__(self, ctx, profiles):
        self.ctx, self.profiles = ctx, profiles
        self.active, self.closed = {}, False

    def _profile(self, provider):
        if provider not in self.profiles:
            raise LlmError('pi-ai adapter does not own provider "{}"'.format(provider), 'NO_ADAPTER')
        return self.profiles[provider]

    def provider_info(self, provider):
        return dict(id=provider, name=self._profile(provider)['displayName'])

    def provider_retry_policy(self, provider):
        return copy.deepcopy(self._profile(provider)['retryPolicy'])

    async def list_models(self, provider):
        return [dict(provider=provider, id=model['id'], name=model['name'], inputModalities=list(model['input']))
                for model in self._profile(provider)['models']]

    async def resolve_model(self, provider, model, signal=None):
        return model_info(self._profile(provider), model)

    async def prepare_call(self, provider, model, signal=None):
        profile = copy.deepcopy(self._profile(provider))
        return dict(model=model_info(profile, model), retryPolicy=copy.deepcopy(profile['retryPolicy']),
                    stream=lambda request: self._stream(request, profile))

    def stream(self, request):
        return self._stream(request, copy.deepcopy(self._profile(request['provider'])))

    async def _stream(self, request, profile):
        if self.closed:
            raise LlmError('pi-ai adapter has been unloaded', 'ABORTED')
        if 'stop' in request:
            raise LlmError('llm-pi-ai does not support GenerateOptions.stop', 'UNSUPPORTED_OPTION')
        model_info(profile, request['model'])
        model = next(row for row in profile['models'] if row['id'] == request['model'])
        effort = resolve_reasoning_level(model, request.get('reasoningEffort', profile.get('reasoning')))
        task = asyncio.current_task()
        done = asyncio.Event()
        self.active[done] = task
        events = None
        try:
            api_key = await resolve_api_key(self.ctx, profile['provider'], profile)
            if self.closed:
                raise LlmError('pi-ai adapter has been unloaded', 'ABORTED')
            on_degrade = lambda reason: logging.getLogger('llm-pi-ai').warning('Unusable replay for %s/%s: %s', profile['provider'], model['id'], reason)
            attachments = self.ctx.get('attachments')
            has_images = any(any(images(message['content'])) for message in request['messages'])
            if has_images and attachments is not None:
                def access(ref):
                    location = getattr(attachments, 'imageHostPath', None)
                    fs = self.ctx.get('fs')
                    mapping = getattr(fs, 'processPathFromHostPath', None)
                    path = location(ref) if location else None
                    return mapping(path) if mapping and path is not None else None
                context = await to_pi_context_with_images(request, attachments, access, profile['maxRequestImageBytes'],
                    dict(maxPixels=profile['requestImagePixelBudget'], maxBytes=profile['requestImageMaxBytes']), on_degrade)
            else:
                context = to_pi_context(request, on_degrade)
            options = {key: profile[key] for key in ('thinkingBudgets', 'cacheRetention', 'transport', 'timeoutMs',
                       'websocketConnectTimeoutMs', 'streamIdleTimeoutMs') if key in profile}
            options.update({key: request[key] for key in ('temperature', 'maxTokens', 'sessionId') if key in request})
            if api_key is not None:
                options['apiKey'] = api_key
            if effort not in (None, 'off'):
                options['reasoning'] = effort
            attribution = attribution_headers()
            reserved = {key.lower() for key in attribution}
            options['headers'] = {key: value for key, value in profile.get('headers', {}).items() if key.lower() not in reserved}
            options['headers'].update(attribution)
            from dsh.llm.pi_completions_stream import completions_events
            owned = OwnedStream(lambda signal: completions_events(model, context, options, signal), request.get('signal'))
            events = iter_chunks(owned)
            async for chunk in to_stream_chunks(events, model['contextWindow'], request.get('signal')):
                yield chunk
        finally:
            if events is not None:
                await events.aclose()
            self.active.pop(done, None)
            done.set()

    async def close(self):
        self.closed = True
        pending = list(self.active.items())
        current = asyncio.current_task()
        for _, task in pending:
            if task is not None and task is not current:
                task.cancel()
        if pending:
            await asyncio.gather(*(done.wait() for done, task in pending if task is not current))
