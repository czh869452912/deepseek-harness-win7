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
        for ref in (None, False, 0, 1, 2, 3, -1, 1.5):
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
    return rows


def native(rows):
    from dsh.session.format_v3_to_v4 import tool_role, sources, content, developer, system_message, message_sources, retired_syntax
    from dsh.session.format_v3_to_v4 import facts, fork_result, references, extension_identities
    modules = (tool_role, sources, content, developer, system_message, message_sources, retired_syntax,
               facts, fork_result, references, extension_identities)
    functions = {name: getattr(module, name) for module in modules for name in dir(module) if not name.startswith('_')}
    results = []
    for row in rows:
        args = copy.deepcopy(row['args'])
        before = copy.deepcopy(args)
        try:
            value = functions[row['operation']](*args)
            results.append(dict(case=row['case'], ok=True, value=value, same=value is args[0] and value is not None, unchanged=before == args,
                                serialized=json.dumps(value, ensure_ascii=False, separators=(',', ':'))))
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
