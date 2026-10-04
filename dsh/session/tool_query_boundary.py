import inspect

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.utils import _UNDEFINED
from dsh.llm.error import HarnessError, _string
from dsh.session.preparations import throw_aborted
from dsh.session.session_query import SessionQueryError


SAFE_FAILURES = {
    'SESSION_QUERY_ABORTED': 'session query was cancelled',
    'SESSION_QUERY_CORRUPT_SESSION': 'session event history is corrupt',
    'SESSION_QUERY_EVENT_NOT_FOUND': 'session event was not found',
    'SESSION_QUERY_INDEX_FAILED': 'session search index is unavailable',
    'SESSION_QUERY_INVALID_CURSOR': 'session search continuation is invalid',
    'SESSION_QUERY_INVALID_FILTER': 'session query filters were rejected',
    'SESSION_QUERY_INVALID_LIMIT': 'session query result limit was rejected',
    'SESSION_QUERY_INVALID_QUERY': 'session query was rejected',
    'SESSION_QUERY_INVALID_LINEAGE': 'session lineage is invalid',
    'SESSION_QUERY_INVALID_SURFACE': 'session event history is invalid',
    'SESSION_QUERY_INVALID_WINDOW': 'session event window is invalid',
    'SESSION_QUERY_PERSISTENCE_FAILED': 'session history storage is unavailable',
    'SESSION_QUERY_SEARCH_DISABLED': 'session search is disabled in this deployment',
    'SESSION_QUERY_SESSION_NOT_FOUND': 'session was not found',
    'SESSION_QUERY_STALE_CURSOR': 'session history changed while paging; retry the complete search call',
}


def unauthorized_target():
    return HarnessError('session target is outside the caller workspace', 'SESSION_QUERY_TOOL_UNAUTHORIZED')


def generic_failure():
    return HarnessError('session query operation failed', 'SESSION_QUERY_TOOL_FAILED')


def full_error(error):
    try:
        diagnostics, seen = [], set()
        while isinstance(error, BaseException) and id(error) not in seen:
            seen.add(id(error))
            stack = getattr(error, 'stack', None)
            diagnostics.append(_string(error) if stack is None else stack)
            error = getattr(error, 'cause', _UNDEFINED)
        if isinstance(error, BaseException):
            diagnostics.append('[circular error cause]')
        elif error is not _UNDEFINED:
            diagnostics.append(_string(error))
        return '\nCaused by: '.join(diagnostics)
    except BaseException:
        return '[unprintable session query failure]'


def sanitize_error(ctx, operation, error):
    generic = generic_failure()
    if isinstance(error, ThrownValueError):
        error = error.value
    diagnostic = full_error(error)
    try:
        ctx.logger.warn('tool-session-query: ' + operation + ' failed: ' + diagnostic)
        if isinstance(error, SessionQueryError):
            code = error.code
            if isinstance(code, str) and code in SAFE_FAILURES:
                return SessionQueryError(SAFE_FAILURES[code], code)
        if isinstance(error, HarnessError) and error.code == 'SESSION_QUERY_TOOL_UNAUTHORIZED':
            return unauthorized_target()
    except BaseException:
        return generic
    return generic


async def call(ctx, signal, operation, invoke):
    throw_aborted(signal)
    try:
        pending = invoke()
        value = await pending if inspect.isawaitable(pending) else pending
        throw_aborted(signal)
        return value
    except BaseException as error:
        throw_aborted(signal)
        raise sanitize_error(ctx, operation, error) from None
