"""Installed current Session boundary used by the build-static format catalog."""
from dsh.core.session.json import UNDEFINED
from dsh.core.session.types import SessionLogOffset
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format_v2_to_v3.payload import display


def require_current(header, format_version=3):
    version = header.get('version', UNDEFINED)
    if not _js_strict_equal(version, format_version):
        raise ValueError('installed Session format is v%s, got v%s' % (format_version, display(version)))


def validateInstalledCurrentSessionHeader(header, format_version=3):
    require_current(header, format_version)
    from dsh.core.session.current_session import CurrentSession
    CurrentSession.from_restore(header.get('id',UNDEFINED), [], header, SessionLogOffset(0), 'detached', format_version=format_version)


def validateInstalledCurrentSessionArtifact(artifact, format_version=3):
    require_current(artifact['header'], format_version)
    from dsh.core.session.current_session import CurrentSession
    # This provider brands the cut before the constructor validates seed events.
    cut = SessionLogOffset(artifact['inheritedEventCount'])
    projections = ()
    if format_version == 4:
        from .message_projections import currentSessionMessageProjections
        projections = currentSessionMessageProjections
    CurrentSession.from_restore(artifact['header'].get('id',UNDEFINED), artifact['events'],
        artifact['header'], cut, 'detached', format_version=format_version,
        projections=projections)
