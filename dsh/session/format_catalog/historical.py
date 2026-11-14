"""Historical child inspection without recursively opening installed Sessions."""
from dsh.session.format import createSessionFormatCatalog
from dsh.session.format_v0_to_v1 import releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, sessionFormatV0ToV1
from dsh.session.format_v1_to_v2 import releasedV2SessionFormatCodec, sessionFormatV1ToV2
from dsh.session.format_v2_to_v3 import assertReleasedV3Header, releasedV3SessionFormatCodec, restoreReleasedV3Artifact, sessionFormatV2ToV3
from dsh.session.format_v3_to_v4 import RELEASED_V3_EVENT_TYPES


def _restore_header(header):
    assertReleasedV3Header(header)
    return header


historicalSessionFormatCatalog = createSessionFormatCatalog(dict(currentVersion=3,
    codecs=[releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, releasedV2SessionFormatCodec, releasedV3SessionFormatCodec],
    currentEncoder=releasedV3SessionFormatCodec, migrations=[sessionFormatV0ToV1, sessionFormatV1ToV2, sessionFormatV2ToV3],
    restoreCurrent=lambda artifact: restoreReleasedV3Artifact(artifact, RELEASED_V3_EVENT_TYPES),
    restoreTransformedCurrent=lambda artifact: restoreReleasedV3Artifact(artifact, RELEASED_V3_EVENT_TYPES),
    restoreCurrentHeader=_restore_header))
