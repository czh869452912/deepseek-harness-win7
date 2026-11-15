"""Shared reconnect baselines and connection-local Assistant arrival cuts."""
from dsh.core.session.types import SessionSeq
from dsh.api.session_assistant_stream_current import SessionAssistantStreamAccumulator


class SessionAssistantStreamsListener:
    def __init__(self, ctx):
        self.ctx, self.streams = ctx, {}
        def assistant(payload):
            session, frame = payload['agent'].session, payload['frame']
            if session.id not in self.streams:
                self.streams[session.id] = SessionAssistantStreamAccumulator()
            self.streams[session.id].accept(frame, -1 if session.seq == 0 else SessionSeq(session.seq - 1))
        ctx.on('agent/assistant-stream', assistant, global_listener=True)
        ctx.on('agent/disposed', lambda payload:self.streams.pop(payload['agent'].session.id, None), global_listener=True)
        ctx.effect(lambda: self.streams.clear, 'session-controller.assistant-streams')

    def bind(self, session_id, signal, queue):
        def snapshot():
            stream = self.streams.get(session_id)
            return stream.snapshot() if stream is not None else dict(revision=0)
        return AssistantStreamListener(self.ctx, session_id, signal, snapshot, queue)


class AssistantStreamListener:
    def __init__(self, ctx, session_id, signal, snapshot, output):
        signal.throwIfAborted()
        self.disposes, self.ordinal, self.cut, self.read_snapshot = [], 0, 0, snapshot
        input = output.createInput(self.transform)
        def assistant(payload):
            session, frame = payload['agent'].session, payload['frame']
            if session.id != session_id:
                return
            def capture():
                wire = (dict(frame, startedAfterSeq=-1 if session.seq == 0 else SessionSeq(session.seq - 1))
                        if frame['type'] == 'start' else frame)
                self.ordinal += 1
                input.append(dict(type='assistant-stream', session=session, frame=wire, ordinal=self.ordinal))
            output.capture(capture)
        try:
            self.disposes.append(ctx.on('agent/assistant-stream', assistant, global_listener=True))
        except BaseException:
            self.dispose()
            raise

    def snapshot(self):
        return dict(baseline=self.read_snapshot(), ordinal=self.ordinal)

    def setOrdinalCut(self, ordinal):
        self.cut = ordinal

    def transform(self, item):
        if self.disposes and item['ordinal'] > self.cut:
            yield dict(type='assistant-stream', frame=item['frame'])

    def dispose(self):
        disposes, self.disposes = self.disposes, []
        for dispose in reversed(disposes):
            dispose()
