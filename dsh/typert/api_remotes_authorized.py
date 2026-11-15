"""Application-owned rc022 event declarations and resource-bearing notifications."""
from dsh.typert.api_remotes import ApiRemotesPlugin
from dsh.typert.current import CurrentForwardedEventSource
from dsh.typert.stores import field
from dsh.core.session.json import UNDEFINED


def session_id(value=UNDEFINED, *_):
    return value


def summary_session(value=UNDEFINED, *_):
    return field(value, 'sessionId', UNDEFINED)


API_REMOTE_FORWARDED_EVENTS = (
    dict(event='agent-preset/selected', mode='emit'),
    dict(event='approval/request', mode='waterfall'),
    dict(event='api-session/activity', mode='emit', resources=dict(session=session_id)),
    dict(event='api-session/added', mode='emit', resources=dict(session=summary_session)),
    dict(event='api-session/error', mode='emit', resources=dict(session=session_id)),
    dict(event='api-session/removed', mode='emit', resources=dict(session=session_id)),
    dict(event='api-session/status', mode='emit', resources=dict(session=session_id)),
    dict(event='commands/change', mode='emit'),
    dict(event='deepseek-account/session-expired', mode='emit'),
    dict(event='deepseek-account/model-sign-in-required', mode='emit'),
    dict(event='credentials/record-updated', mode='emit'),
    dict(event='credentials/reference-updated', mode='emit'),
    dict(event='goal/activation-changed', mode='emit'),
    dict(event='cordis/request-run', mode='emit'),
    dict(event='cordis/request-run-resolved', mode='emit'),
    dict(event='cordis/dynamic-package', mode='emit'),
    dict(event='cordis/dynamic-retract', mode='emit'),
    dict(event='cordis/inspect-query', mode='emit'),
    dict(event='cordis/inspect-query-resolved', mode='emit'),
    dict(event='llm/adapters-updated', mode='emit'),
    dict(event='llm/models-updated', mode='emit'),
    dict(event='permission-presets/catalog-changed', mode='emit'),
    dict(event='plugin-manager/changed', mode='emit'),
    dict(event='plugin-manager/install-log', mode='emit'),
    dict(event='plugin-manager/install-state', mode='emit'),
    dict(event='plugin-manager/update-state', mode='emit'),
    dict(event='plugin-market/changed', mode='emit'),
    dict(event='settings/document-updated', mode='emit'),
    dict(event='schedule/changed', mode='emit'),
    dict(event='user-questions/request', mode='waterfall'),
    dict(event='web/providers-changed', mode='emit'),
)


class AuthorizedForwardedEventSource(CurrentForwardedEventSource):
    emit_events = tuple(entry['event'] for entry in API_REMOTE_FORWARDED_EVENTS if entry['mode'] == 'emit')
    resources = {entry['event']: entry['resources'] for entry in API_REMOTE_FORWARDED_EVENTS if 'resources' in entry}

    def push(self, frame):
        readers = self.resources.get(frame['event'])
        if readers is not None and 'context' not in frame:
            frame = dict(frame, resources=readers)
        return super().push(frame)


class AuthorizedApiRemotes(ApiRemotesPlugin):
    source_class = AuthorizedForwardedEventSource
