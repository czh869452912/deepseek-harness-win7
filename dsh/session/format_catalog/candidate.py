"""Explicit target catalog; production selection changes with its storage users."""
from dsh.core.session.current_vocabulary import V4_SESSION_EVENT_TYPES
from dsh.session.format import createSessionFormatCatalog
from dsh.session.format_v0_to_v1 import releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, sessionFormatV0ToV1
from dsh.session.format_v1_to_v2 import releasedV2SessionFormatCodec, sessionFormatV1ToV2
from dsh.session.format_v2_to_v3 import releasedV3SessionFormatCodec, sessionFormatV2ToV3
from dsh.session.format_v3_to_v4 import (assertReleasedV4Header, releasedV4SessionFormatCodec,
    restoreReleasedV4Artifact, sessionFormatV3ToV4, createSessionFormatV3ToV4)
from .current import validateInstalledCurrentSessionArtifact, validateInstalledCurrentSessionHeader


def restore_current(artifact):
    restored = restoreReleasedV4Artifact(artifact, V4_SESSION_EVENT_TYPES)
    validateInstalledCurrentSessionArtifact(restored, 4)
    return restored


def restore_header(header):
    assertReleasedV4Header(header)
    validateInstalledCurrentSessionHeader(header, 4)
    return header


sessionFormatCatalogOptions = dict(currentVersion=4,
    codecs=[releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, releasedV2SessionFormatCodec,
            releasedV3SessionFormatCodec, releasedV4SessionFormatCodec],
    currentEncoder=releasedV4SessionFormatCodec,
    migrations=[sessionFormatV0ToV1, sessionFormatV1ToV2, sessionFormatV2ToV3, sessionFormatV3ToV4],
    restoreCurrent=restore_current,
    restoreTransformedCurrent=lambda artifact: restoreReleasedV4Artifact(artifact, V4_SESSION_EVENT_TYPES),
    restoreCurrentHeader=restore_header)

candidateSessionFormatCatalog = createSessionFormatCatalog(sessionFormatCatalogOptions)


def createSessionFormatCatalogWithChildren(children):
    edge = createSessionFormatV3ToV4(children)
    return createSessionFormatCatalog(dict(sessionFormatCatalogOptions,
        migrations=[edge if item is sessionFormatV3ToV4 else item for item in sessionFormatCatalogOptions['migrations']]))
