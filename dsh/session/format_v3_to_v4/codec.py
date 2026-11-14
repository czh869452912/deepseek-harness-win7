"""Released physical framing with V4 guards before recoverable-tail decoding."""
from dsh.core.session.json import UNDEFINED, FrozenDict
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError
from dsh.session.format.chain import call
from dsh.session.format_v1_to_v2 import releasedV2SessionFormatCodec
from .developer import assertV4DeveloperData
from .fork_result import assertV4ForkResult
from .message_sources import assertV4SourceRowAdmission
from .retired_syntax import assertV4RetiredSyntax
from .system_message import assertV4SystemMessageFields
from .tool_role import assertV4ToolResultMessage
from .validation import assertReleasedV4Header


def _physical_v2(value):
    if not isinstance(value, dict) or not _js_strict_equal(value.get('version', UNDEFINED), 4):
        raise SessionFormatError('expected format v4 physical header')
    return dict(value, version=2)


def assertV4RowAdmission(row, knownEventTypes=None):
    if isinstance(row, dict):
        if (row.get('type') == 'developer/message' and row.get('ignorable') is True
                and (knownEventTypes is None or 'developer/message' not in knownEventTypes)):
            return
        assertV4DeveloperData(row)
    assertV4SourceRowAdmission(row)
    assertV4RetiredSyntax(row)
    assertV4SystemMessageFields(row)
    if not isinstance(row, dict) or row.get('type') != 'tool/result':
        return
    assertV4ToolResultMessage(row)
    assertV4ForkResult(row)


def decodeHeader(value):
    return dict(call(releasedV2SessionFormatCodec, 'decodeHeader', _physical_v2(value)), version=4)


class ReleasedV4Decoder:
    def __init__(self, value, recovery):
        self.decoder = call(releasedV2SessionFormatCodec, 'createDecoder', _physical_v2(value), recovery)
        self.header = dict(self.decoder.header, version=4)

    def decodeRow(self, row, context):
        assertV4RowAdmission(row)
        self.decoder.decodeRow(row, context)

    def finish(self, context):
        return self.decoder.finish(context)


def encodeHeader(header, inheritedEventCount):
    assertReleasedV4Header(header)
    return dict(call(releasedV2SessionFormatCodec, 'encodeHeader', dict(header, version=2), inheritedEventCount), version=4)


def encodeEvent(event):
    if event['type'] == 'developer/message' and event.get('ignorable') is True:
        assertV4DeveloperData(event)
        assertV4RetiredSyntax(event)
    assertV4RowAdmission(event)
    return call(releasedV2SessionFormatCodec, 'encodeEvent', event)


releasedV4SessionFormatCodec = FrozenDict(version=4, decodeHeader=decodeHeader,
    createDecoder=ReleasedV4Decoder, encodeHeader=encodeHeader, encodeEvent=encodeEvent)
