"""Explicit V3 to V4 edge, bound to one parent's complete child evidence."""
from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.format import SessionFormatError, SessionFormatUnsupportedMigrationError, defineSessionFormatMigration, sessionFormatCount
from dsh.session.format.chain import call, member
from dsh.session.format_v0_to_v1.payload import compact
from dsh.session.format_v2_to_v3 import assertReleasedV3Header
from .content import migrateV3EventContent
from .extension_identities import namespaceV3OpaqueEvent, RELEASED_V3_EVENT_TYPES
from .facts import catalogFact, childCatalogSource, childCatalogFact, childCatalogSubject
from .references import remapV3References
from .sources import mapEventMessages, rewriteV3MessageSource
from .tool_role import liftToolResult
from .validation import assertReleasedV4Header, validateDeliveryAccepted


class ReleasedV3ToV4Stage:
    def __init__(self, source, children):
        self.input = source
        self.header = member(source, 'sourceHeader')
        # JavaScript string order compares UTF-16 code units, including astral names.
        self.candidates = sorted([childCatalogSource(child) for child in children],
            key=lambda child: (child['childCreatedAt'], child['childId'].encode('utf-16-be', errors='surrogatepass')))
        self.catalogs, self.mapping = [], []
        self.cut = UNDEFINED if self.header['isSeeded'] else 0
        self.source_cut = self.cut
        if not self.header['isSeeded']:
            self.headerInheritedEventCount = 0
        self.turn, self.foreign_delivery = UNDEFINED, UNDEFINED
        self.step_open, self.next_turn_spliced, self.next_seq = False, False, 0
        self.time = self.header['createdAt']

    def transformEvent(self, event, context):
        if not _js_strict_equal(event['seq'], len(self.mapping)):
            raise SessionFormatError('V3 source events must be dense')
        interrupted = self.observe_restart(event)
        if interrupted is not UNDEFINED:
            call(context, 'emitEvent', dict(type='turn/end', seq=self.next_seq, time=event['time'],
                data=dict(turn=interrupted, reason=dict(kind='interrupted'))))
            self.next_seq += 1
        target_seq = self.next_seq
        self.next_seq += 1
        self.time = event['time']
        data = event['data']
        if event['type'] == 'session/end-seed' and isinstance(data, dict) and data.get('inherited') is True:
            if not self.header['isSeeded']:
                raise SessionFormatError('unseeded format v3 Session contains an inherited end-seed marker')
            self.source_cut, self.cut = event['seq'], target_seq
            self.catalogs.clear()
        elif event['type'] == 'subagent/catalog':
            self.catalogs.append(data)
        delivery_id = validateDeliveryAccepted(event, 3)
        if event['type'] == 'session-log-deepseek/delivery-accepted':
            if _js_strict_equal(data.get('sessionFormatVersion', UNDEFINED), 4):
                raise SessionFormatUnsupportedMigrationError('format v3 delivery marker claims target format v4')
            if delivery_id is not None and delivery_id != self.header['id']:
                self.foreign_delivery = event['seq']
        opaque = namespaceV3OpaqueEvent(event)
        if opaque is not event:
            self.mapping.append(target_seq)
            call(context, 'emitEvent', opaque if _js_strict_equal(opaque['seq'], target_seq) else dict(opaque, seq=target_seq))
            return
        if event['type'] not in RELEASED_V3_EVENT_TYPES:
            raise SessionFormatUnsupportedMigrationError('format v3 contains unknown event type ' + compact(event['type']) + ' at seq ' + str(event['seq']))
        remapped = remapV3References(event, target_seq, self.mapping)
        self.mapping.append(target_seq)

        def rewrite(message):
            source = message.get('source')
            if not isinstance(source, dict):
                return message
            converted = rewriteV3MessageSource(source, event['seq'], message.get('role', UNDEFINED))
            return message if converted is source else dict(message, source=converted)

        call(context, 'emitEvent', migrateV3EventContent(liftToolResult(mapEventMessages(remapped, rewrite))))

    def transformRun(self, run, context):
        for event in call(run, 'expand'):
            self.transformEvent(event, context)

    def observe_restart(self, event):
        data, kind = event['data'], event['type']
        interrupted = self.turn if (kind == 'turn/start' and self.turn is not UNDEFINED and not self.step_open
            and self.next_turn_spliced and isinstance(data, dict)
            and _js_strict_equal(data.get('turn', UNDEFINED), self.turn + 1)) else UNDEFINED
        self.next_turn_spliced = (kind == 'agent/inbox/spliced' and isinstance(data, dict)
            and data.get('target') == 'next-turn' and isinstance(data.get('inserted'), list) and len(data['inserted']) > 0)
        if kind == 'turn/start' and isinstance(data, dict) and type(data.get('turn')) in (int, float):
            self.turn = data['turn']
        elif kind == 'turn/end':
            self.turn = UNDEFINED
        elif kind == 'step/start':
            self.step_open = True
        elif kind == 'step/end':
            self.step_open = False
        return interrupted

    def finish(self, context):
        cut = sessionFormatCount(self.cut, 'V3 inherited event count')
        source_cut = sessionFormatCount(self.source_cut, 'V3 source inherited event count')
        existing_catalogs = {}
        for data in self.catalogs:
            fact = catalogFact(data); identity = fact['childId']
            if identity in existing_catalogs:
                raise SessionFormatUnsupportedMigrationError('duplicate catalog child ' + identity)
            existing_catalogs[identity] = fact
        supplied = member(self.input, 'sourceInheritedEventCount')
        if supplied is not UNDEFINED and not _js_strict_equal(source_cut, supplied):
            raise SessionFormatError('format v3 inherited cut disagrees with its source marker')
        if self.foreign_delivery is not UNDEFINED and (self.header.get('parentSession', UNDEFINED) is UNDEFINED or self.foreign_delivery >= source_cut):
            raise SessionFormatError('current-generation delivery marker names the wrong Session')
        for source in self.candidates:
            identity = source['childId']
            existing = existing_catalogs.get(identity)
            fact = childCatalogFact(source)
            if existing is not None:
                if (not _js_strict_equal(existing['childCreatedAt'], source['childCreatedAt'])
                        or fact is not None and any(not _js_strict_equal(existing.get(key, UNDEFINED), fact.get(key, UNDEFINED)) for key in ('mode', 'label'))):
                    raise SessionFormatUnsupportedMigrationError(childCatalogSubject(source) + ' conflicts with its parent catalog')
                continue
            entry = fact if fact is not None else dict(version=1, childId=identity, childCreatedAt=source['childCreatedAt'], mode='unknown')
            existing_catalogs[identity] = entry
            call(context, 'emitEvent', dict(type='subagent/catalog', seq=self.next_seq, time=self.time, data=entry))
            self.next_seq += 1
        return cut


def _header(header):
    assertReleasedV3Header(header)
    return dict(header, version=4)


def _unbound_stage(source):
    raise SessionFormatUnsupportedMigrationError('V3 catalog migration requires explicit historical child facts, including an empty array for a parent without children')


sessionFormatV3ToV4 = defineSessionFormatMigration(dict(name='@deepseek-ai/dsh-session-format-v3-to-v4',
    fromVersion=3, toVersion=4, migrateHeader=_header, createStage=_unbound_stage, validateTargetHeader=assertReleasedV4Header))


def createSessionFormatV3ToV4(children):
    return defineSessionFormatMigration(dict(sessionFormatV3ToV4, createStage=lambda source: ReleasedV3ToV4Stage(source, children)))
