"""Host job Remote owner, preserving the model's cursor and notice state."""
from dsh.cordis.schema import Schema
from dsh.cordis.utils import js_to_string
from dsh.cordis.errors import ThrownValueError
from dsh.llm.error import HarnessError
from dsh.typert.remote import Remote, RemoteError, TypertRemoteService
from .observe_current import stream_job_rows, observe_job_output


class CurrentJobController(TypertRemoteService):
    inject = ['jobs', 'typert']
    Config = Schema.object(dict(observeFlushMs=Schema.natural().min(1).default(100),
                                observeMaxFrameBytes=Schema.natural().min(1).default(65536)))

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'jobController', dict(namespace='job'))
        config = config or {}
        self.flush_ms = config.get('observeFlushMs', 100)
        self.max_frame_bytes = config.get('observeMaxFrameBytes', 65536)

    @Remote(dict(mode='stream'))
    def list(self, request, signal):
        return stream_job_rows(self.ctx.jobs, request, dict(flushMs=self.flush_ms), signal)

    @Remote(dict(mode='stream'))
    def follow(self, request, signal):
        return observe_job_output(self.ctx.jobs, request, dict(flushMs=self.flush_ms, maxFrameBytes=self.max_frame_bytes), signal)

    @Remote('kill')
    def kill(self, request):
        jobs = self.ctx.jobs
        try:
            jobs.get(request['jobId'], request['sessionId'])
        except Exception as error:
            # Native HarnessError.__str__ includes a code prefix; JS Error's
            # String conversion uses only its name and message.
            if isinstance(error, HarnessError):
                message = (error.name + ': ' if error.name else '') + error.message
            elif type(error) is RuntimeError:
                message = 'Error: ' + str(error) if str(error) else 'Error'
            else:
                message = js_to_string(error.value if isinstance(error, ThrownValueError) else error)
            raise RemoteError('job/not-found', message, dict(sessionId=request['sessionId'],jobId=request['jobId']))
        return dict(outcome=jobs.kill(request['jobId'], request['sessionId'], 'cancelled by the user'))
