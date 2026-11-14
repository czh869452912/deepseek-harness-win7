"""Pair the candidate value helpers with fixed Source, without changing the pin."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'


def cases():
    from dsh.session.format_v3_to_v4.sources import RENAMED_PRODUCERS, RELEASED_SAME_NAME_PRODUCERS
    rows = []

    def add(operation, *args):
        rows.append(dict(case='{}-{}'.format(operation, len(rows)), operation=operation, args=copy.deepcopy(list(args))))

    def event(kind, data):
        return dict(type=kind, seq=7, time=9, data=data)

    message = dict(id='result', role='user', source=dict(kind='tool', callId='call'),
                   content=[dict(type='tool-result', toolCallId='call', content=[dict(type='text', text='中文')])])
    for error in ('absent', False, True, None, 0, 1, '', 'false'):
        value = copy.deepcopy(message)
        if error != 'absent':
            value['content'][0]['isError'] = error
        value.update({'__proto__': {'x': 1}, 'constructor': 'saved', 'toolCallId': 'outer', 'isError': 'opaque'})
        value['content'][0].update({'__proto__': [1], 'constructor': True, 'plugin:message:x': None})
        add('liftToolResult', event('tool/result', dict(turn=1, step=1, message=value)))
    for key, values in {'id': [None, '', 0], 'source': [None, [], {}, {'kind': 'tool', 'callId': ''}, {'kind': 'user', 'callId': 'call'}],
                        'content': [None, [], [None], [{}, {}], [dict(type='tool-result', toolCallId='wrong', content=[])]]}.items():
        for value in values:
            item = copy.deepcopy(message); item[key] = value
            add('liftToolResult', event('tool/result', dict(message=item)))
    for content in ([], None, {}, [dict(type='tool-result', content=[])], [None], [dict(type='plugin:test', args={'type': 'tool-result'})]):
        item = copy.deepcopy(message); item['content'][0]['content'] = content
        add('liftToolResult', event('tool/result', dict(message=item)))
    for kind in ('other', 'tool/result'):
        for data in (None, [], {}, dict(message={'role': 'tool'})):
            add('liftToolResult', event(kind, data))
    native = dict(role='tool', source=dict(kind='tool', callId='call'), toolCallId='call', content=[], id='id')
    for key, values in {'id': [None, '', 0, 'id'], 'role': ['user', 'tool'], 'toolCallId': ['call', 'other', 0],
                        'source': [None, {}, {'kind': 'wrong', 'callId': 'call'}],
                        'isError': [None, 0, 1, False, True], 'content': [None, {}, [], [dict(type='tool-result')]]}.items():
        for value in values:
            item = dict(native); item[key] = value
            add('assertV4ToolResultMessage', event('tool/result', dict(message=item)))
    for error in (None, False, True):
        for flag in (False, True):
            add('assertV4ToolResultMessage', event('tool/result', dict(message=dict(native, isError=flag), error=error)))
    for data in (None, {}, {'message': None}, {'message': native}):
        add('assertV4ToolResultMessage', event('tool/result', data))
    for plugin in sorted(set(RENAMED_PRODUCERS) | RELEASED_SAME_NAME_PRODUCERS | {'', 'custom', 'plugin:x', '__proto__', 'constructor'}):
        for role in ('system', 'user'):
            add('rewriteV3MessageSource', dict(kind='plugin', plugin=plugin, extra={'nested': 'saved'}), 7, role)
    for source in ({}, {'kind': ''}, {'kind': False}, {'kind': 'plugin'}, {'kind': 'plugin', 'plugin': None},
                   {'kind': 'user', 'plugin': 'opaque'}, {'kind': 'custom', 'value': [1]}):
        add('rewriteV3MessageSource', source, 7, 'user')
    for content in ([], None, {}, [None], [{}], [{'type': 3}], [{'type': ''}], [{'type': 'plugin:x'}],
                    [{'type': 'text', 'text': '中文'}], [{'type': 'tool-call', 'arguments': {'type': 'opaque'}}]):
        add('migrateV3Content', content, 'subject')
    for kind in ('user/message', 'developer/message', 'system/message', 'assistant/message', 'tool/result',
                 'agent/inbox/spliced', 'session/title-llm-request', 'team/message/queued', 'other'):
        for content in ([], [dict(type='custom', value={'type': 'text'})], None):
            msg = dict(content=content)
            data = msg if kind == 'user/message' else dict(message=msg, inserted=[msg], messages=[msg])
            add('migrateV3EventContent', event(kind, data))
    for kind in ('compaction/summary', 'tool/ptc-dispatch', 'assistant/attempt'):
        add('migrateV3EventContent', event(kind, dict(summary=[dict(type='custom')], rawOutput=[], content=[],
            stream=[dict(type='chunk', chunk=dict(type='block-start', blockType='custom')),
                    dict(type='chunk', chunk=dict(type='block-end', block=dict(type='plugin:custom', value=3)))])))
    for kind in ('block-start', 'block-end', 'other'):
        for value in (None, 0, '', 'text', 'unknown'):
            add('migrateV3EventContent', event('assistant/attempt', dict(stream=[dict(type='chunk', chunk=dict(type=kind, blockType=value, block=value))])))
    for tool in ({}, {'deferLoading': None}, {'deferLoading': False}, {'parameters': {'deferLoading': True}}, None):
        add('migrateV3EventContent', event('request/header', dict(header=dict(tools=[tool]))))
    for operation in ('assertV4MessageSources', 'assertV4SourceRowAdmission', 'assertV4RetiredSyntax', 'assertV4DeveloperData'):
        for kind in ('user/message', 'system/message', 'developer/message', 'assistant/message', 'tool/result',
                     'agent/inbox/spliced', 'session/title-llm-request', 'team/message/queued', 'unknown'):
            for source in (None, {}, {'kind': ''}, {'kind': 'plugin', 'plugin': 'goal'}, {'kind': 'plugin:goal'}, {'kind': 'custom'}):
                msg = dict(id='m', role='user', source=source, content=[])
                data = msg if kind == 'user/message' else dict(turn=1, step=1, message=msg, inserted=[msg], messages=[msg])
                add(operation, event(kind, data))
        for data in (None, [], {}, {'message': None}):
            add(operation, event('developer/message', data))
    developer = dict(type='developer/message', seq=1, data=dict(turn=1, step=1,
        message=dict(id='d', role='developer', source={'kind': 'tools'}, content=[])))
    for contents in ([], [None], [dict(type='text')], [dict(type='tool-removal', toolName='x')],
                     [dict(type='tool-addition', toolName='x')], [dict(type='tool-addition', toolName='')],
                     [dict(type='tool-addition', toolName='x', tool=None)]):
        for header in ('absent', None, False, 0, 1, -1, 1.5, 9007199254740992):
            value = copy.deepcopy(developer); value['data']['message']['content'] = contents
            if header != 'absent':
                value['data']['headerSeq'] = header
            add('assertV4DeveloperData', value)
    for kind in ('user/message', 'assistant/message', 'compaction/summary', 'assistant/attempt', 'unknown'):
        for tag in ('tool-addition', 'tool-removal', 'tool-result', 'text'):
            block = dict(type=tag, toolName='x')
            msg = dict(role='developer', content=[block])
            data = msg if kind == 'user/message' else dict(message=msg, summary=[block], rawOutput=[block],
                stream=[dict(type='chunk', chunk=dict(type='block-start', blockType=tag)),
                        dict(type='chunk', chunk=dict(type='block-end', block=block))])
            for operation in ('assertV4DeveloperData', 'assertV4RetiredSyntax'):
                add(operation, event(kind, data))
    for flag in ('absent', None, False, True, 0, 1):
        tool = {} if flag == 'absent' else dict(deferLoading=flag)
        add('assertV4DeveloperData', event('request/header', dict(header=dict(tools=[tool]))))
    for kind in ('tool/code-dispatch', 'tool/code-dispatch-start', 'tool/ptc-dispatch'):
        for flag in (None, False, True, 0, 1):
            add('assertV4RetiredSyntax', dict(event(kind, {}), ignorable=flag))
    for data in (None, {}, {'header': None}, {'header': {}}, {'header': {'system': None}}, {'header': {'opaque': {'system': 1}}}):
        add('assertV4RetiredSyntax', event('request/header', data))
    system = dict(type='system/message', seq=1, data=dict(turn=1, step=1,
        message=dict(id='s', role='system', content=[])))
    for field in ('turn', 'step'):
        for value in (None, False, True, 0, 1, -1, 1.5, 9007199254740991, 9007199254740992):
            row = copy.deepcopy(system); row['data'][field] = value
            add('assertV4SystemMessageFields', row)
            row = copy.deepcopy(developer); row['data'][field] = value
            add('assertV4DeveloperData', row)
    image = dict(type='image', attachment=dict(attachmentId='a', mediaType='image/png', bytes=0, width=1, height=1))
    for contents in (None, {}, [None], [{}], [dict(type='')], [dict(type='text', text='')], [dict(type='reasoning', text=1)],
                     [dict(type='tool-call', id='c', name='t', arguments='{}')], [dict(type='tool-result')],
                     [dict(type='plugin:opaque', nested={'type': 'tool-result'})], [image]):
        row = copy.deepcopy(system); row['data']['message']['content'] = contents
        add('assertV4SystemMessageFields', row)
    for field, values in {'attachmentId': [None, ''], 'mediaType': ['image/svg+xml', 'image/webp'],
                          'bytes': [False, -1, 1.5], 'width': [0, True], 'name': [None, '', 5],
                          'originalDimensions': [None, {}, {'width': 1, 'height': 2}]}.items():
        for value in values:
            row = copy.deepcopy(system); block = copy.deepcopy(image); block['attachment'][field] = value
            row['data']['message']['content'] = [block]
            add('assertV4SystemMessageFields', row)
    for version in (None, False, True, 0, 1, 2, 3, '1'):
        for mode in ('continuable', 'one-shot', 'external', 'unknown'):
            value = dict(version=version, childId='child', childCreatedAt=0, mode=mode, label='')
            add('catalogFact', value)
            source = dict(childId='child', childCreatedAt=0, descriptorCount=1,
                          descriptor=dict(version=version, provider='provider', mode=mode, label='label'))
            add('childCatalogSource', source)
            add('childCatalogFact', source)
    for count in (None, False, True, 0, 1, 2, 1.5, -1):
        for descriptor in (None, {}, {'version': 1}, {'version': 1, 'provider': '', 'label': ''},
                           {'version': 3, 'provider': 'p', 'mode': 'one-shot', 'label': None}):
            source = dict(childId='child', childCreatedAt=0, descriptorCount=count, descriptor=descriptor, sourcePath='C:/logs/child')
            add('childCatalogFact', source)
            add('childCatalogSource', source)
    for origin in (None, 'subagent'):
        for parent in ('absent', None, 'parent'):
            for cut in (0, 1, 2):
                header = dict(id='child', origin=origin, createdAt=0)
                if parent != 'absent':
                    header['parentSession'] = parent
                add('historicalChildCatalogSource', dict(header=header, inheritedEventCount=cut,
                    events=[dict(type='subagent/descriptor', seq=0, data=dict(version=1, provider='p', label='L'))]))
    for kind in ('command/done', 'compaction/summary', 'session/title', 'image/offload', 'opaque'):
        for ref in (None, False, 0, 1, 1.0, 2, 3, -1, 1.5):
            row = event(kind, dict(sourceEventSeq=ref, shadowedRange=dict(start=ref, end=ref, opaque=9),
                shadowedSeqs=[ref], messageSeqs=[ref], targets=[dict(seq=ref, width=2)], numericPayload=2))
            row['seq'] = 3
            for target in (3, 4):
                add('remapV3References', row, target, [0, 2, 3])
    for surface in ('append', None, {}, dict(op='replace', startSeq=1, endSeq=2, opaque=3)):
        row = dict(event('opaque', {'number': 2}), seq=3, surfaceOp=surface, sourceEventSeqs=[1, 2])
        add('remapV3References', row, 4, [0, 2, 3])
    for kind in ('user/message', 'custom', 'plugin:custom', 'developer/message', 'tool/code-dispatch'):
        for flag in (False, True, 1):
            add('namespaceV3OpaqueEvent', dict(event(kind, {'opaque': {'seq': 1}}), ignorable=flag))
    fork = dict(type='tool/result', seq=2, surfaceOp='append', data=dict(error=dict(code='TOOL_NOT_STARTED', name='ToolNotStartedError'),
        message=dict(id='forked-tool-result-call-2', role='tool', isError=True, source=dict(kind='tool', callId='call'),
                     toolCallId='call', content=[dict(type='text', text='not started')])))
    for seq in (None, False, True, 0, 1, 2, 3, 2.5):
        for suffix in ('0', '1', '2', '02', '-1', '1.0', '9007199254740992'):
            for replacement in (False, True):
                row = copy.deepcopy(fork); row['seq'] = seq; row['data']['message']['id'] = 'forked-tool-result-call-' + suffix
                if replacement:
                    row.update(surfaceOp={'op': 'replace'}, sourceEventSeqs=[1])
                add('assertV4ForkResult', row)
    header = dict(version=4, id='parent', createdAt=1, isSeeded=False, delegationDepth=0)
    for field, values in {'version': [None, False, True, 3, 4.0], 'id': [None, '', 1], 'createdAt': [-1, False, 1.0],
                          'isSeeded': [None, 0, True], 'cwd': [None, 'relative', 'C:/absolute', '/root'],
                          'origin': [None, 'subagent'], 'parentSession': [None, 'p'], 'extra': [True]}.items():
        for value in values:
            item = dict(header); item[field] = value
            add('assertReleasedV4Header', item)
    for field in header:
        item = dict(header); del item[field]
        add('assertReleasedV4Header', item)
    for version in (None, False, 0, 3, 4, 5):
        for through in (None, False, 0, 7):
            for current in (3, 4):
                add('validateDeliveryAccepted', event('session-log-deepseek/delivery-accepted',
                    dict(sessionFormatVersion=version, throughSeq=through, sessionId='parent')), current)

    def row(kind, data, **extra):
        return dict(type=kind, data=data, **extra)

    def coordinates(events):
        return [dict(value, seq=index, time=index+10) for index, value in enumerate(events)]

    def artifact(events, **extra):
        return dict(header=header, inheritedEventCount=0, events=coordinates(events), **extra)

    user = dict(id='u', role='user', source={'kind': 'user'}, content=[dict(type='text', text='human')])
    start = row('turn/start', {'turn': 1}); step = row('step/start', {'turn': 1, 'step': 1})
    end_step = row('step/end', {'turn': 1, 'step': 1}); end_turn = row('turn/end', {'turn': 1})
    request = row('request/header', dict(header=dict(config={'provider': 'mock'}, tools=[])))
    system_row = row('system/message', dict(turn=1, step=1, message=dict(id='s', role='system',
        source={'kind': 'system-prompt'}, content=[])), surfaceOp='append')
    user_row = row('user/message', user, surfaceOp='append')
    assistant = row('assistant/message', dict(turn=1, step=1, message=dict(id='a', role='assistant', source={'kind': 'llm'},
        content=[dict(type='tool-call', id='call', name='read', arguments='{}')])), surfaceOp='append')
    tool_call = row('tool/call', dict(turn=1, step=1, callId='call', name='read', arguments='{}'))
    tool_result = row('tool/result', dict(turn=1, step=1, message=dict(id='r', role='tool', source=dict(kind='tool', callId='call'),
        toolCallId='call', content=[dict(type='text', text='ok')])), surfaceOp='append')
    ordinary = [start, step, system_row, user_row, request, assistant, tool_call, tool_result, end_step, end_turn]
    known = sorted({value['type'] for value in ordinary} | {'developer/message','subagent/catalog','session/end-seed',
        'compaction/start','compaction/summary','compaction/prune','compaction/end','llm/retry','llm/retry-started',
        'command/run','command/done','session/title','session/title-llm-request','tool/ptc-dispatch-start','tool/ptc-dispatch'})
    for length in range(len(ordinary)+1):
        add('restoreReleasedV4Artifact', artifact(ordinary[:length]), known)
    for index in range(len(ordinary)):
        add('restoreReleasedV4Artifact', artifact(ordinary[:index]+ordinary[index+1:]), known)
    for index, fields in ((0, ('turn',)), (1, ('turn','step')), (6, ('turn','step','callId','name','arguments')), (8, ('turn','step'))):
        for field in fields:
            for value in (None, False, 0, 1.0, 2, 'wrong'):
                changed = copy.deepcopy(ordinary); changed[index]['data'][field] = value
                add('restoreReleasedV4Artifact', artifact(changed), known)
    for field in ('headerSeq', 'turn', 'step'):
        for value in (None, False, 0, 1, 2, 4, 99):
            changed = copy.deepcopy(developer)
            changed['data'].update(headerSeq=2)
            changed['data']['message']['content'] = [dict(type='tool-addition', toolName='read')]
            changed['data'][field] = value
            definition = dict(name='read', description='read files', parameters={})
            declared = row('request/header', dict(header=dict(config={'provider': 'mock'}, tools=[definition])))
            add('restoreReleasedV4Artifact', artifact([start, step, declared, changed]), known)
    compact_rows = [start, user_row, row('compaction/start', dict(compactionId='c', turn=1)),
        row('compaction/summary', dict(compactionId='c', shadowedRange={'start': 1,'end': 1}, shadowedSeqs=[1], summary=[])),
        row('user/message', dict(user, source=dict(kind='compact-checkpoint', compactionId='c')), surfaceOp=dict(op='replace',startSeq=1,endSeq=1), sourceEventSeqs=[1,2,3]),
        row('compaction/end', dict(compactionId='c', turn=1)), end_turn]
    for length in range(len(compact_rows)+1):
        add('restoreReleasedV4Artifact', artifact(compact_rows[:length]), known)
    for index in (2,3,4,5):
        changed = copy.deepcopy(compact_rows)
        owner = changed[index]['data']['source'] if index == 4 else changed[index]['data']
        owner['compactionId'] = 'wrong'
        add('restoreReleasedV4Artifact', artifact(changed), known)
    for provider in ('mock', 'other'):
        for attempt in (0, 1, 2):
            retry = row('llm/retry', dict(turn=1, step=1, retryId='retry', retry=attempt, provider=provider, policyKey='policy'))
            retry_start = row('llm/retry-started', dict(turn=1, step=1, retryId='retry', retry=attempt))
            for suffix in ([retry], [retry,retry_start], [retry,retry_start,retry_start], [retry,retry]):
                add('restoreReleasedV4Artifact', artifact([start, step, request]+suffix), known)
    dispatch = dict(rootCallId='root', parentCallId='root', subCallId='child', name='read', arguments={'a':1,'b':2})
    for changes in ({}, {'arguments': {'b':2,'a':1}}, {'arguments': {'a':True,'b':2}}, {'rootCallId':'other'}, {'parentCallId':'other'}):
        add('restoreReleasedV4Artifact', artifact([start,row('tool/ptc-dispatch-start',dispatch),row('tool/ptc-dispatch',dict(dispatch,**changes))]),known)
    for names in (['alpha','beta'], ['alpha','alpha'], ['lead','beta'], ['a'*33,'beta']):
        catalogs = [row('subagent/catalog', dict(version=3, childId=str(i),childCreatedAt=i,mode='external',name=name)) for i,name in enumerate(names)]
        add('restoreReleasedV4Artifact', artifact(catalogs), known)
    for opaque in (row('custom', {'arbitrary':True},ignorable=True), row('custom',{},ignorable=False), row('developer/message', [],ignorable=True)):
        add('restoreReleasedV4Artifact', artifact([opaque]), [])
    for source_kind in ('user', 'plugin:external'):
        title_input = row('user/message', dict(user, source={'kind':source_kind}), surfaceOp='append')
        for refs in ([], [0], [0,0], [1]):
            add('restoreReleasedV4Artifact', artifact([title_input,row('session/title', dict(source={'kind':'llm'},messageSeqs=refs))]),known)
    v3_header = dict(header, version=3)
    splice = row('agent/inbox/spliced',dict(target='next-turn',inserted=[user]))
    restart = [start, step, end_step, splice, row('turn/start',{'turn':2}),row('turn/end',{'turn':2})]
    child_sources = [dict(childId='late', childCreatedAt=2, descriptorCount=0, descriptor=None),
        dict(childId='early', childCreatedAt=1, descriptorCount=1, descriptor=dict(version=1,provider='p',label='child'))]
    for events in ([], restart, restart[:4], ordinary, [row('custom',{'opaque':1},ignorable=True)], [row('custom',{})]):
        for children in ([], child_sources):
            for runs in (False, True):
                add('migrateV3Stage', dict(sourceHeader=v3_header), children, coordinates(events), False, runs)
    add('migrateV3Stage', dict(sourceHeader=v3_header), [], [], True)
    for cut in (None, 0, 1, 4, 5):
        seeded = dict(v3_header,isSeeded=True,parentSession='p')
        stage_input = dict(sourceHeader=seeded)
        if cut is not None:
            stage_input['sourceInheritedEventCount']=cut
        add('migrateV3Stage',stage_input,child_sources,coordinates(restart+[row('session/end-seed',{'inherited':True})]))
    for children in (child_sources, child_sources+[dict(child_sources[0],childCreatedAt=99)]):
        add('migrateV3Stage',dict(sourceHeader=v3_header),children,coordinates([row('subagent/catalog',dict(version=1,childId='late',childCreatedAt=2,mode='unknown'))]))
    physical = dict(type='session',**header)
    for mode in ('strict', 'recover-tail'):
        for events in (coordinates(ordinary), coordinates(ordinary[:4])+[{'broken':True}],
                       coordinates(ordinary[:4])+[{'broken':True},dict(type='request/header',data={'header':{'system':None}})],
                       [dict(type='developer/message',seq=0,time=1,data=[],ignorable=True)]):
            add('v4DecodeRows',physical,events,mode)
    add('v4DecodeHeader',physical)
    add('v4EncodeHeader',header,0)
    for item in coordinates(ordinary):
        add('v4EncodeEvent',item)
    return rows


def native(rows):
    from dsh.session.format_v0_to_v1.payload import compact
    from dsh.session.format_v3_to_v4 import tool_role, sources, content, developer, system_message, message_sources, retired_syntax
    from dsh.session.format_v3_to_v4 import facts, fork_result, references, extension_identities
    from dsh.session.format_v3_to_v4 import validation, relationships, migration, codec
    modules = (tool_role, sources, content, developer, system_message, message_sources, retired_syntax,
               facts, fork_result, references, extension_identities, validation, relationships, migration, codec)
    functions = {name: getattr(module, name) for module in modules for name in dir(module) if not name.startswith('_')}
    functions.update(v4DecodeHeader=codec.decodeHeader, v4EncodeHeader=codec.encodeHeader, v4EncodeEvent=codec.encodeEvent)

    def migrate_stage(stage_input, children, events, unbound=False, runs=False):
        declaration = migration.sessionFormatV3ToV4 if unbound else migration.createSessionFormatV3ToV4(children)
        emitted, result = [], {}
        result['events'] = emitted
        from dsh.session.format.chain import SessionFormatEventCollector
        context = SessionFormatEventCollector(); context.values = emitted
        try:
            result['header'] = declaration['migrateHeader'](stage_input['sourceHeader'])
            stage = declaration['createStage'](stage_input)
            if runs:
                stage.transformRun(dict(expand=lambda: events), context)
            else:
                for event in events:
                    stage.transformEvent(event, context)
            result['inheritedEventCount'] = stage.finish(context)
            if hasattr(stage, 'headerInheritedEventCount'):
                result['headerInheritedEventCount'] = stage.headerInheritedEventCount
        except Exception as error:
            result['error'] = dict(name=getattr(error, 'name', type(error).__name__), message=str(error))
        return result

    def decode_rows(header, rows, recovery):
        from dsh.session.format.chain import SessionFormatEventCollector
        context = SessionFormatEventCollector(); result = dict(events=context.values)
        try:
            decoder = codec.ReleasedV4Decoder(header, recovery)
            result['header'] = decoder.header
            for row in rows:
                decoder.decodeRow(row, context)
            result['inheritedEventCount'] = decoder.finish(context)
        except Exception as error:
            result['error'] = dict(name=getattr(error, 'name', type(error).__name__), message=str(error))
        return result

    functions.update(migrateV3Stage=migrate_stage, v4DecodeRows=decode_rows)
    results = []
    for row in rows:
        args = copy.deepcopy(row['args'])
        before = copy.deepcopy(args)
        try:
            value = functions[row['operation']](*args)
            results.append(dict(case=row['case'], ok=True, value=value, same=value is args[0] and value is not None, unchanged=before == args,
                                serialized=compact(value)))
        except Exception as error:
            results.append(dict(case=row['case'], ok=False, name=getattr(error, 'name', type(error).__name__), message=str(error), unchanged=before == args))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.relative_to(ROOT / '.goose/out')
    output.mkdir(exist_ok=False, parents=True)
    def git(*words):
        return subprocess.check_output(['git', '-C', str(source)] + list(words), encoding='utf-8', timeout=30).strip()
    assert git('rev-parse', 'HEAD') == TARGET
    assert not git('status', '--porcelain', '--untracked-files=no')
    rows = cases()
    (output/'cases.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    command = [str(args.node.resolve()), str(source/'node_modules/tsx/dist/cli.mjs'), '--tsconfig', str(source/'tsconfig.base.json'),
               str(ROOT/'scripts/oracles/rc022_format_values.mts'), str(source), str(output/'cases.json')]
    result = subprocess.run(command, capture_output=True, timeout=120)
    (output/'source.json').write_bytes(result.stdout)
    (output/'source.stderr').write_bytes(result.stderr)
    report = dict(target_upstream=TARGET, command=command, source_exit_code=result.returncode,
                  scope='Pure candidate value helpers only; not v4 migration, native admission or production persistence')
    try:
        if result.returncode:
            raise RuntimeError('Source observer failed; see source.stderr')
        observed, local = json.loads(result.stdout), native(rows)
        (output/'native.json').write_text(json.dumps(local, ensure_ascii=False), encoding='utf-8')
        from scripts.session_format_oracle import json_equal
        assert len(observed) == len(local) == len(rows)
        differences = [dict(case=row['case'], source=a, native=b) for row,a,b in zip(rows,observed,local) if not json_equal(a,b)]
        report.update(cases=len(rows), differences=differences, matched=len(rows)-len(differences))
        assert not differences, 'Source/native differences'
        report['status'] = 'passed'
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        inputs = list((source/'packages/session/session-format-v3-to-v4/src').glob('*.ts'))
        inputs += list((ROOT/'dsh/session/format_v3_to_v4').glob('*.py'))
        inputs += [ROOT/'scripts/oracles/rc022_format_values.mts', Path(__file__).resolve(), output/'cases.json']
        report['inputs'] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], matched=report['matched'])))


if __name__ == '__main__':
    main()
