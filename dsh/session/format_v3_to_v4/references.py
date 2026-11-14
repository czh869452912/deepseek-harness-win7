"""Remap only released local references when insertion moves an event."""
from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError, sessionFormatCount


def _object(value):
    if not isinstance(value, dict):
        raise SessionFormatError('V3 event reference container must be an object')
    return value


def remapV3References(event, seq, mapping):
    if _js_strict_equal(seq, event['seq']):
        return event

    def reference(value):
        source = sessionFormatCount(value, 'V3 source event reference')
        if source >= event['seq'] or source >= len(mapping):
            raise SessionFormatError('V3 reference must name an earlier source event')
        return mapping[int(source)]

    def references(value):
        if not isinstance(value, list):
            raise SessionFormatError('V3 event references must be an array')
        return [reference(item) for item in value]

    data, kind = event.get('data', UNDEFINED), event['type']
    if kind == 'command/done':
        source = _object(data)
        if source.get('sourceEventSeq', UNDEFINED) is not UNDEFINED:
            data = dict(source, sourceEventSeq=reference(source['sourceEventSeq']))
    elif kind in ('compaction/summary', 'compaction/prune'):
        source = _object(data); area = _object(source.get('shadowedRange'))
        data = dict(source, shadowedRange=dict(area, start=reference(area.get('start', UNDEFINED)),
                    end=reference(area.get('end', UNDEFINED))), shadowedSeqs=references(source.get('shadowedSeqs')))
    elif kind in ('session/title', 'session/title-llm-request'):
        source = _object(data)
        data = dict(source, messageSeqs=references(source.get('messageSeqs')))
    elif kind == 'image/offload':
        source = _object(data); targets = source.get('targets')
        if not isinstance(targets, list):
            raise SessionFormatError('V3 image offload targets must be an array')
        data = dict(source, targets=[dict(_object(item), seq=reference(_object(item).get('seq', UNDEFINED))) for item in targets])
    surface = event.get('surfaceOp', UNDEFINED)
    area = None if surface is UNDEFINED or surface == 'append' else _object(surface)
    value = dict(event, seq=seq, data=data)
    if event.get('sourceEventSeqs', UNDEFINED) is not UNDEFINED:
        value['sourceEventSeqs'] = references(event['sourceEventSeqs'])
    if area is not None:
        value['surfaceOp'] = dict(area, startSeq=reference(area.get('startSeq', UNDEFINED)), endSeq=reference(area.get('endSeq', UNDEFINED)))
    return value
