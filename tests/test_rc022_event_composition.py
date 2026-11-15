import pytest

from dsh.core.session.json import UNDEFINED
from dsh.typert.api_remotes_authorized import API_REMOTE_FORWARDED_EVENTS
from dsh.typert.access import event_resources
from scripts.rc022_event_composition_probe import observe


@pytest.mark.asyncio
async def test_actual_application_events_http_answers_and_websocket_generations():
    rows = {row['name']: row for row in await observe()}
    assert len(rows) == 9
    assert len(rows['allowlist']['entries']) == 31
    frames = rows['all-broadcasts']
    assert len(frames['ownerA']) == len(frames['ownerB']) == 29
    assert len(frames['guest']) == 5
    assert all(frame['event'].startswith('api-session/') for frame in frames['guest'])
    answer = rows['http-answer-binding']
    assert answer['foreign']['body']['result']['error']['code'] == 'gateway/interactions-forbidden'
    assert answer['own']['body']['result'] == dict(ok=True)
    assert answer['settlement'] == dict(value=dict(approved=True))
    assert answer['cancelled'] == dict(type='cancel', sameEvent=True)
    assert answer['fallback'] == 0
    assert rows['delegation-waits'] == dict(name='delegation-waits', pending=True, fallback=0)
    assert rows['delegation-next']['settlement'] == dict(value=dict(fallback=True))
    assert rows['delegation-next']['fallback'] == 1
    assert rows['application-unload']['frames'] == [dict(type='end', streamId='a'), dict(type='end', streamId='b')]
    assert rows['application-reload']['distinctGeneration'] is True
    assert rows['application-reload']['notification']['value'] == dict(type='emit', event='plugin-manager/changed', args=[dict(revision=2)])


@pytest.mark.parametrize('event', ['api-session/activity', 'api-session/added', 'api-session/error', 'api-session/removed', 'api-session/status'])
@pytest.mark.parametrize('identity', ['session-a', '', None, UNDEFINED])
def test_application_session_resources_reject_missing_identity(event, identity):
    entry = next(entry for entry in API_REMOTE_FORWARDED_EVENTS if entry['event'] == event)
    args = [dict(sessionId=identity)] if event.endswith('/added') else [identity]
    actual = event_resources(entry['resources'], args)
    assert actual == ([dict(kind='session', id=identity)] if identity == 'session-a' else None)
