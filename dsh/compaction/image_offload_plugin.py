"""Durable image-budget repair for Agent and compaction summary requests."""
from dsh.cordis.plugin import Plugin
from dsh.core.cancellation import aborted
from dsh.core.abort import abort_reason_error
from dsh.llm.llm_service import LlmError
from dsh.compaction.image_offload import imageOffloadProjection, offloadOldestImages

IMAGE_OFFLOAD_REQUIRED_CODE = 'IMAGE_OFFLOAD_REQUIRED'


class CurrentImageOffload(Plugin):
    id = 'compaction-image-offload'
    inject = ['agents', 'sessions']

    def apply(self, ctx):
        ctx.sessions.registerMessageProjection(imageOffloadProjection)

        async def request_error(payload, next_fn):
            failure, signal = payload['failure'], payload['signal']
            if failure.get('code') != IMAGE_OFFLOAD_REQUIRED_CODE or 'offloadImages' not in failure or aborted(signal):
                return await next_fn()
            session = payload['agent'].session
            if not offloadOldestImages(session, session.surface.nodes, failure['offloadImages']):
                return await next_fn()
            return dict(kind='retry')

        async def summary_error(payload, next_fn):
            error, signal = payload['error'], payload.get('signal')
            if not isinstance(error, LlmError) or error.code != IMAGE_OFFLOAD_REQUIRED_CODE or 'offloadImages' not in error.failure:
                return await next_fn()
            if aborted(signal):
                raise abort_reason_error(signal)
            if not offloadOldestImages(payload['session'], payload['sourceEventSeqs'], error.failure['offloadImages']):
                return await next_fn()
            return True

        ctx.on('agent/request-error', request_error)
        ctx.on('compaction/summary-error', summary_error)
