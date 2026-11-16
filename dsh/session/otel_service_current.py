"""Cordis factory for independently owned ordinary-event and Session channels."""
from dsh.cordis.service import Service
from dsh.session.otel_event_channel_current import EventLogReporter
from dsh.session.otel_http_current import SessionHttpExporter
from dsh.session.otel_records_current import resolve_session_log_limits
from dsh.session.otel_session_channel_current import SessionLogReporter


class CurrentOTel(Service):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'otel')

    def createEventReporter(self, options):
        return EventLogReporter(options)

    def createSessionLogReporter(self, options):
        resolve_session_log_limits(options)
        return SessionLogReporter(options, SessionHttpExporter(options['exporter']))
