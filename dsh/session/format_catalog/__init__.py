"""Build-static first-party Session format catalog, independent of plugin mounts."""
from dsh.core.session.current_vocabulary import KNOWN_SESSION_EVENT_TYPES
from dsh.session.format import createSessionFormatCatalog, SessionFormatUnsupportedMigrationError
from dsh.session.format_v0_to_v1 import releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, sessionFormatV0ToV1
from dsh.session.format_v1_to_v2 import releasedV2SessionFormatCodec, sessionFormatV1ToV2
from dsh.session.format_v2_to_v3 import assertReleasedV3Header, releasedV3SessionFormatCodec, restoreReleasedV3Artifact, sessionFormatV2ToV3
from .current import validateInstalledCurrentSessionArtifact, validateInstalledCurrentSessionHeader
from .historical import historicalSessionFormatCatalog
from .candidate import candidateSessionFormatCatalog, createSessionFormatCatalogWithChildren


def restore_current(artifact):
    restored = restoreReleasedV3Artifact(artifact, KNOWN_SESSION_EVENT_TYPES)
    validateInstalledCurrentSessionArtifact(restored)
    return restored


def restore_header(header):
    assertReleasedV3Header(header)
    validateInstalledCurrentSessionHeader(header)
    return header


sessionFormatCatalog = createSessionFormatCatalog(dict(currentVersion=3,
    codecs=[releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, releasedV2SessionFormatCodec, releasedV3SessionFormatCodec],
    currentEncoder=releasedV3SessionFormatCodec, migrations=[sessionFormatV0ToV1, sessionFormatV1ToV2, sessionFormatV2ToV3],
    restoreCurrent=restore_current,
    restoreTransformedCurrent=lambda artifact: restoreReleasedV3Artifact(artifact, KNOWN_SESSION_EVENT_TYPES),
    restoreCurrentHeader=restore_header))
