"""Canonical v3 surface transitions and protected system-head ownership."""
from dsh.core.session.json import UNDEFINED
from dsh.core.surface import _assert_tool_result_rewrite
from .current import safe, SURFACE_EVENT_TYPES, V4_SURFACE_EVENT_TYPES, validateSessionEventData
from .current_vocabulary import KNOWN_SESSION_EVENT_TYPES, V4_SESSION_EVENT_TYPES, MESSAGE_PROJECTION_EVENT_TYPES


def provenance(event, shadowed):
    raw, seq = event.get('sourceEventSeqs', UNDEFINED), event['seq']
    if event['type'] == 'assistant/message' and raw is not UNDEFINED:
        raise ValueError('assistant/message embeds its source stream and cannot carry sourceEventSeqs')
    sources = set()
    if raw is not UNDEFINED:
        if not isinstance(raw, list):
            raise ValueError('sourceEventSeqs on event at seq %s must be an array when present' % seq)
        if not raw:
            raise ValueError('sourceEventSeqs must not be empty')
        non_earlier = None
        for value in raw:
            if not safe(value, True, True):
                raise ValueError('session event "%s" sourceEventSeqs must densely contain non-negative safe integers' % event['type'])
            sources.add(value)
            if non_earlier is None and value >= seq:
                non_earlier = value
        if len(sources) != len(raw):
            raise ValueError('sourceEventSeqs must not contain duplicates')
        if non_earlier is not None:
            raise ValueError('sourceEventSeqs must reference earlier events: %s >= current seq %s' % (non_earlier, seq))
    missing = [seq for seq in shadowed if seq not in sources]
    if missing:
        raise ValueError('surface replace: sourceEventSeqs must include every shadowed surface node; missing ' + ', '.join(str(seq) for seq in missing))


def validateSurfaceMetadata(event, format_version=3):
    kind = event['type']
    eligible = V4_SURFACE_EVENT_TYPES if format_version == 4 else SURFACE_EVENT_TYPES
    known = V4_SESSION_EVENT_TYPES if format_version == 4 else KNOWN_SESSION_EVENT_TYPES
    if kind not in eligible:
        if kind not in known and event.get('ignorable') is True:
            return None
        for key in ('surfaceOp', 'sourceEventSeqs'):
            if event.get(key, UNDEFINED) is not UNDEFINED:
                raise ValueError('session event "%s" is not surface-eligible and cannot carry %s' % (kind, key))
        return None
    operation = event.get('surfaceOp', UNDEFINED)
    if operation is UNDEFINED:
        raise ValueError('session event "%s" is surface-eligible and requires a surfaceOp marker' % kind)
    if operation != 'append':
        if not isinstance(operation, dict):
            raise ValueError('session event "%s" carries an invalid surfaceOp' % kind)
        if (set(operation) != {'op', 'startSeq', 'endSeq'} or operation['op'] != 'replace'
                or not safe(operation['startSeq'], True, True) or not safe(operation['endSeq'], True, True)):
            raise ValueError('session event "%s" carries an invalid replace surfaceOp' % kind)
        if operation['startSeq'] >= event['seq'] or operation['endSeq'] >= event['seq']:
            raise ValueError('surface replace at seq %s: startSeq and endSeq must reference earlier events' % event['seq'])
    provenance(event, [])
    return operation


class CurrentSurface:
    def __init__(self, events, base_seq=0, format_version=3, projections=()):
        self.events, self.base_seq = events, base_seq
        self.nodes, self.replaceGeneration = [], 0
        self.format_version, self.projections = format_version, projections
        self.contentGeneration, self.projectedMessages, self.used_projections = 0, {}, []

    def plan(self, event, expected, candidates=()):
        if type(event['seq']) not in (int, float) or event['seq'] != expected:
            raise ValueError('session event seq %s is not contiguous; expected %s' % (event['seq'], expected))
        operation = validateSurfaceMetadata(event, self.format_version)
        if self.format_version == 4:
            self._developer_header(event, candidates)
            projection = next((item for item in self.projections if item['type'] == event['type']), None)
            if projection is not None:
                from types import SimpleNamespace
                events = self.events if not candidates else [*self.events, *candidates]
                messages = projection['project'](event, SimpleNamespace(nodes=self.nodes, events=events,
                    baseSeq=self.base_seq, messages=self.projectedMessages))
                return dict(kind='project', projection=projection, messages=messages)
            if event['type'] in MESSAGE_PROJECTION_EVENT_TYPES:
                raise ValueError('session event "%s" requires a message projection; load its owning plugin or supply its projection definition' % event['type'])
        if operation is None or operation == 'append':
            return operation
        start, end = operation['startSeq'], operation['endSeq']
        if start not in self.nodes:
            raise ValueError('surface replace: start seq %s not found in surface' % start)
        if end not in self.nodes:
            raise ValueError('surface replace: end seq %s not found in surface' % end)
        first, last = self.nodes.index(start), self.nodes.index(end)
        if first > last:
            raise ValueError('surface replace: start seq %s (index %s) is after end seq %s (index %s)' % (start, first, end, last))
        shadowed = self.nodes[first:last+1]
        provenance(event, shadowed)
        if self.format_version == 4:
            self._tool_rewrite(event, shadowed, candidates)
        else:
            _assert_tool_result_rewrite(event, shadowed, self.events, self.base_seq)
        if first == 0 and self._read(self.nodes[0], candidates)['type'] == 'system/message' and (event['type'] != 'system/message' or len(shadowed) != 1):
            raise ValueError('surface replace: node 0 holds the system prompt and may be rewritten only by a system/message over exactly that node')
        return first, last

    def apply(self, event, plan):
        if plan == 'append':
            self.nodes.append(event['seq'])
        elif isinstance(plan, dict) and plan.get('kind') == 'project':
            self.projectedMessages.update(plan['messages'])
            if not any(item is plan['projection'] for item in self.used_projections):
                self.used_projections.append(plan['projection'])
            self.contentGeneration += 1
        elif plan is not None:
            first, last = plan
            self.nodes[first:last+1] = [event['seq']]
            self.replaceGeneration += 1
            self.contentGeneration += 1

    def _read(self, seq, candidates=()):
        index = seq-self.base_seq
        if index < 0:
            return None
        if index < len(self.events):
            return self.events[int(index)]
        index -= len(self.events)
        return candidates[int(index)] if index < len(candidates) else None

    def _developer_header(self, event, candidates=()):
        if event['type'] != 'developer/message':
            return
        validateSessionEventData(event, 'developer/message at seq %s' % event['seq'], 4)
        seq = event['data'].get('headerSeq', UNDEFINED)
        if seq is UNDEFINED:
            return
        header = self._read(seq, candidates)
        if seq >= event['seq'] or header is None or header['type'] != 'request/header':
            raise ValueError('developer/message headerSeq must reference an earlier request/header')
        for block in event['data']['message']['content']:
            if not isinstance(block, dict) or block.get('type') != 'tool-addition':
                continue
            definitions = [tool for tool in header['data']['header'].get('tools', []) if tool.get('name') == block['toolName']]
            if len(definitions) != 1:
                raise ValueError('developer/message tool-addition "%s" must name exactly one tool in headerSeq %s' % (block['toolName'], seq))
            definition = definitions[0]
            if not isinstance(definition.get('description'), str) or not isinstance(definition.get('parameters'), dict):
                raise ValueError('developer/message tool-addition "%s" requires a complete tool definition in headerSeq %s' % (block['toolName'], seq))
            if 'deferLoading' in definition and definition['deferLoading'] is not True:
                raise ValueError('developer/message referenced tool deferLoading must be true when present')

    def _tool_rewrite(self, event, shadowed, candidates=()):
        if event['type'] != 'tool/result':
            return
        if len(shadowed) != 1:
            raise ValueError('tool/result surface replacement must rewrite exactly one current node')
        original = self._read(shadowed[0], candidates)
        if original['type'] != 'tool/result':
            raise ValueError('tool/result surface replacement must target a current tool/result')
        from dsh.session.format_v0_to_v1.payload import equal_json
        before, after = dict(original['data']), dict(event['data'])
        before['message'] = dict(before['message'], content=None)
        after['message'] = dict(after['message'], content=None)
        if not equal_json(before, after):
            raise ValueError('tool/result surface replacement may change only content')


def deriveEventMessage(event, projected_messages=None, format_version=3):
    if projected_messages is not None and event['seq'] in projected_messages:
        return projected_messages[event['seq']]
    kind, data = event['type'], event['data']
    if kind == 'user/message':
        return data
    if kind in ('system/message', 'assistant/message') or format_version == 4 and kind == 'developer/message':
        return data['message'] if data['message']['content'] else None
    if kind == 'tool/result':
        return data['message']
    return None


class CurrentSurfaceManager:
    """Incremental acceptance, retaining only the next exact candidate plan."""
    def __init__(self, log, base_seq=0, format_version=3, projections=()):
        self.log, self.base_seq = log, base_seq
        self.fold = CurrentSurface(log, base_seq, format_version, projections)
        self.last = base_seq-1
        self.pending = None

    def validate_next(self, event):
        self._assert_projections()
        self._sync()
        expected = self.base_seq+len(self.log)
        self.pending = (event, expected, self.fold.plan(event, expected))

    validateNext = validate_next

    def prepareBatch(self, events):
        self._sync()
        start = self.base_seq+len(self.log)
        simple = all(event.get('surfaceOp', UNDEFINED) in (UNDEFINED, 'append')
                     and not any(item['type'] == event['type'] for item in self.fold.projections) for event in events)
        if simple:
            plans = [self.fold.plan(event, start+index, events) for index, event in enumerate(events)]
        else:
            temporary = CurrentSurface(self.log, self.base_seq, self.fold.format_version, self.fold.projections)
            temporary.nodes = list(self.fold.nodes)
            temporary.replaceGeneration, temporary.contentGeneration = self.fold.replaceGeneration, self.fold.contentGeneration
            temporary.projectedMessages = dict(self.fold.projectedMessages)
            temporary.used_projections = list(self.fold.used_projections)
            plans = []
            for index, event in enumerate(events):
                plan = temporary.plan(event, start+index, events)
                temporary.apply(event, plan)
                plans.append(plan)
        def accept():
            for event, plan in zip(events, plans):
                self.fold.apply(event, plan)
            self.last = start+len(events)-1
            self.pending = None
        return accept

    def _sync(self):
        self._assert_projections()
        for seq in range(self.last+1, self.base_seq+len(self.log)):
            event = self.log[seq-self.base_seq]
            pending = self.pending
            plan = pending[2] if pending is not None and pending[0] is event and pending[1] == seq else self.fold.plan(event, seq)
            self.fold.apply(event, plan)
            if pending is not None and pending[1] <= seq:
                self.pending = None
            self.last = seq

    def _assert_projections(self):
        required = list(self.fold.used_projections)
        pending = self.pending
        if (pending is not None and pending[1]-self.base_seq < len(self.log)
                and self.log[pending[1]-self.base_seq] is pending[0]
                and isinstance(pending[2], dict) and pending[2].get('kind') == 'project'):
            required.append(pending[2]['projection'])
        for projection in required:
            if not any(item is projection for item in self.fold.projections):
                raise ValueError('session message projection "%s" was removed or replaced; restore the session with its owning plugin' % projection['type'])

    @property
    def contentGeneration(self):
        self._sync()
        return self.fold.contentGeneration

    def deriveEventMessage(self, event):
        self._sync()
        return deriveEventMessage(event, self.fold.projectedMessages, self.fold.format_version)

    @property
    def nodes(self):
        self._sync()
        return self.fold.nodes

    @property
    def replaceGeneration(self):
        self._sync()
        return self.fold.replaceGeneration

    @property
    def replace_generation(self):
        return self.replaceGeneration


def foldSurface(events, projections=(), format_version=3):
    surface = CurrentSurface(events, format_version=format_version, projections=projections)
    replacements = []
    for index, event in enumerate(events):
        plan = surface.plan(event, index)
        if plan is not None and plan != 'append' and not isinstance(plan, dict):
            first, last = plan
            replacements.append(dict(seq=event['seq'], start=event['surfaceOp']['startSeq'],
                end=event['surfaceOp']['endSeq'], shadowedSeqs=list(surface.nodes[first:last+1])))
        surface.apply(event, plan)
    result = dict(nodes=list(surface.nodes), replacements=replacements)
    if format_version == 4:
        result['projectedMessages'] = dict(surface.projectedMessages)
    return result
