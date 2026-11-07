"""Retained observer identity with bounded current Source/runtime checks."""
import argparse
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PIN = 'a4c74a91e06b00fe0b0937bde982170c526cc842'
REQUIRED = {'grammar', 'mentions', 'searches', 'positions', 'outline', 'changes', 'orders',
            'searchLimits', 'indexed', 'checkpoint', 'lineage', 'storageLineage', 'strictHeaders',
            'projectionLineage', 'turnBoundary', 'turnBoundaryEvents', 'chunkDecode', 'chunkPack',
            'scheduleProjection', 'scheduleStates', 'retryProjection'}
CURRENT_MODULES = {'dsh/core/session/current_session.py', 'dsh/core/session/current_surface.py',
                   'dsh/core/system_prompt/current.py', 'dsh/session/jsonl_current.py',
                   'dsh/session/format_v0_to_v1/codec.py', 'dsh/llm/assistant_stream.py'}


def digest(value):
    def numbers(item):
        if type(item) is float and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: numbers(child) for key, child in item.items()}
        if isinstance(item, list):
            return [numbers(child) for child in item]
        return item
    return hashlib.sha256(json.dumps(numbers(value), sort_keys=True, ensure_ascii=True,
                                    allow_nan=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def validate_runtime(report, root, source_digest, input_digest, modules=None):
    root = Path(root).resolve()
    executable = root / 'python.exe' if modules is not None or (root / 'python.exe').is_file() else Path(sys.executable)
    if (not isinstance(report, dict) or report.get('root') != str(root)
            or Path(report.get('executable', '')).resolve() != executable.resolve()
            or report.get('python') != [3, 8, 10] or report.get('sourcePin') != PIN
            or report.get('sourceObservationsSha256') != source_digest
            or report.get('inputSha256') != input_digest
            or set(report.get('observations', {})) != REQUIRED
            or digest(report['observations']) != source_digest
            or not isinstance(report.get('modules'), dict) or not CURRENT_MODULES.issubset(report['modules'])
            or (modules is not None and report['modules'] != modules)):
        raise ValueError('rc.1 observations or runtime identity differ')
    if modules is None:
        for name, expected in report['modules'].items():
            path = (root / name).resolve()
            if root / 'dsh' not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('rc.1 runtime imported foreign or changed bytes')


def observe_runtime(inputs, root, input_digest):
    sys.path.insert(0, str(root))
    import time
    clock = time.time
    time.time = lambda: inputs['clock'] / 1000
    try:
        rows = asyncio.run(native(inputs))
    finally:
        time.time = clock
    modules = {}
    for name, module in list(sys.modules.items()):
        if name == 'dsh' or name.startswith('dsh.'):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                relative = path.relative_to(root)
                modules[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(root=str(root), executable=sys.executable, python=list(sys.version_info[:3]),
                sourcePin=PIN, observations=rows, sourceObservationsSha256=digest(rows),
                inputSha256=input_digest, modules=modules)


def source_inputs(source):
    tracked = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z']).decode('utf-8').rstrip('\0').split('\0')
    paths = set(tracked)
    for manifest in tracked:
        if Path(manifest).name == 'package.json':
            library = (source / manifest).parent / 'lib'
            if library.is_dir():
                paths.update(path.relative_to(source).as_posix() for path in library.rglob('*')
                             if path.is_file() and 'node_modules' not in path.relative_to(library).parts)
    paths.add('.dsh-build/client-build-environment.json')
    # Every byte is read on each pass. Bound concurrent opens so filesystem
    # latency cannot consume the observer budget before either runtime starts.
    def observe(name):
        return name, hashlib.sha256((source / name).read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=8) as workers:
        return dict(workers.map(observe, sorted(paths)))


async def native(inputs):
    from dsh.cordis.context import Context
    from dsh.context.file_reference import active_at_token, format_file_mention
    from dsh.context.file_reference_local.search import WorkspaceFileSearch
    from dsh.core.session import SessionSeq, SessionLogOffset
    from dsh.core.session.current_session import CurrentSession as Session, CurrentSessionStore as SessionStore
    from dsh.core.session.types import validate_session_header
    from dsh.session.jsonl_current import toHeaderLine as to_header_line, SessionLogScanner, scanLog
    from dsh.core.session.json import UNDEFINED
    from dsh.core.system_prompt.current import CurrentSystemPrompt as SystemPrompt
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.session.turn_outline import TURN_OUTLINE_DEFINITION
    rows = dict(grammar=[], mentions=[], searches=[], positions=[], outline=[], changes=[], orders={})
    from dsh.session.format_v0_to_v1.codec import releasedV1SessionFormatCodec
    from dsh.llm.assistant_stream import AssistantStreamAccumulator
    from types import SimpleNamespace
    rows['chunkDecode'] = []
    for row in inputs['chunkRecords']:
        try:
            events = []
            decoder = releasedV1SessionFormatCodec['createDecoder'](dict(type='session', version=1, id='legacy-chunks', createdAt=1, delegationDepth=0), 'strict')
            context = SimpleNamespace(emitEvent=events.append, emitRun=lambda run: events.extend(run['expand']()))
            decoder.decodeRow(row, context)
            decoder.finish(context)
            rows['chunkDecode'].append(dict(events=events))
        except (ValueError, TypeError) as error:
            rows['chunkDecode'].append(dict(error=str(error)))
    rows['chunkPack'] = []
    for events in inputs['chunkBatches']:
        accumulator = AssistantStreamAccumulator()
        for event in events:
            accumulator.push(dict(time=event['time'], chunk=event['data']['chunk']))
        rows['chunkPack'].append(accumulator.snapshot())
    from dsh.schedule.projection import SCHEDULE_DEFINITION, schedule_state
    from dsh.llm.llm_retry import RETRY_DEFINITION
    rows['scheduleStates'] = []
    for value in inputs['scheduleStates']:
        try:
            rows['scheduleStates'].append(dict(accepted=True, state=schedule_state(value)))
        except (ValueError, TypeError):
            rows['scheduleStates'].append(dict(accepted=False))
    rows['scheduleProjection'] = []
    for cut in (0, 1):
        state = SCHEDULE_DEFINITION['init'](None, cut)
        values = []
        for event in inputs['scheduleEvents']:
            state = SCHEDULE_DEFINITION['apply'](state, event)
            values.append(state)
        rows['scheduleProjection'].append(values)
    state = RETRY_DEFINITION['init'](None, 0)
    rows['retryProjection'] = []
    for event in inputs['retryEvents']:
        state = RETRY_DEFINITION['apply'](state, event)
        rows['retryProjection'].append(state)
    from dsh.core.turn_boundary import boundary_state, apply_boundary, TURN_BOUNDARY_DEFINITION
    rows['turnBoundary'] = []
    for state in inputs['boundaryStates']:
        try:
            rows['turnBoundary'].append(dict(accepted=True, state=boundary_state(state)))
        except (ValueError, TypeError, KeyError):
            rows['turnBoundary'].append(dict(accepted=False))
    state = TURN_BOUNDARY_DEFINITION['init'](None, 0)
    rows['turnBoundaryEvents'] = []
    for event in inputs['boundaryEvents']:
        state = apply_boundary(state, event)
        rows['turnBoundaryEvents'].append(state)
    def scalar(token):
        return -0.0 if token == '-0' else json.loads(token)
    rows['lineage'] = []
    for row in inputs['lineage']:
        try:
            cut = scalar(row['cut']) if 'cut' in row else UNDEFINED
            constructor = Session.fromRestore if row.get('mode') == 'restore' else Session.create
            arguments = (row['header']['id'], row.get('seed'), row['header'], cut)
            session = constructor(*arguments, event_state='detached') if row.get('mode') == 'restore' else constructor(*arguments)
            rows['lineage'].append(dict(header=session.header.to_dict(), firstLiveSeq=session.firstLiveSeq,
                inheritedEventCount=session.inheritedEventCount, seq=session.seq, owned=session.ownEvents(),
                ownPositions=[session.isOwnSeq(seq) for seq in (-1, 0, 1, 2, 3, session.seq)]))
        except (ValueError, TypeError) as error:
            rows['lineage'].append(dict(error=str(error)))
    rows['storageLineage'] = []
    for row in inputs['storageLineage']:
        try:
            physical = row['physical'] if 'physical' in row else to_header_line(
                row['header'], scalar(row['cut']) if 'cut' in row else UNDEFINED)
            line = json.dumps(physical)
            raw = (line + '\n').encode('utf-8')
            parsed = dict(meta=SessionLogScanner(raw).meta)
            scanned = scanLog(raw)
            rows['storageLineage'].append(dict(physical=physical,
                parsed=parsed,
                scanned=dict(meta=scanned['meta'], inheritedEventCount=scanned['inheritedEventCount'])))
        except (ValueError, TypeError) as error:
            rows['storageLineage'].append(dict(error=str(error)))
    rows['strictHeaders'] = []
    for row in inputs['strictHeaders']:
        header = dict(row)
        if header.get('seedLength') == 'UNDEFINED':
            header['seedLength'] = UNDEFINED
        try:
            rows['strictHeaders'].append(dict(header=validate_session_header('child', header, expected_version=3).to_dict()))
        except (ValueError, TypeError) as error:
            rows['strictHeaders'].append(dict(error=str(error)))
    for row in inputs['tokens']:
        token = active_at_token(row['line'], row['cursor'])
        rows['grammar'].append(token.to_dict() if token else None)
    rows['mentions'] = [format_file_mention(row['candidate'], row['quote']) for row in inputs['mentions']]
    search = WorkspaceFileSearch(inputs['workspace'])
    try:
        for query in inputs['queries']:
            rows['searches'].append(await search.list(query))
    finally:
        search.dispose()
        await search.drain()
    rows['searchLimits'] = []
    for config in inputs['searchConfigs']:
        try:
            configured = WorkspaceFileSearch(inputs['workspace'], config)
            try:
                rows['searchLimits'].append(dict(accepted=True, candidates=await configured.list('py')))
            finally:
                configured.dispose()
                await configured.drain()
        except ValueError as error:
            rows['searchLimits'].append(dict(accepted=False, error=str(error)))
    for brand in (SessionSeq, SessionLogOffset):
        for token in inputs['positions']:
            value = -0.0 if token == '-0' else json.loads(token)
            row = dict(name=brand.__name__, token=token)
            try:
                row['value'] = brand(value)
            except TypeError as error:
                row['error'] = str(error)
            rows['positions'].append(row)
    ctx = Context()
    try:
        await ctx.plugin(SessionStore)
        await ctx.plugin(SessionProjectionRegistry)
        await ctx.plugin(SystemPrompt)
        registry = ctx.get('sessionProjections')
        registry.register(TURN_OUTLINE_DEFINITION)
        registry.onChanged(lambda _s, _k, value, seq: rows['changes'].append(dict(seq=seq, value=value)))
        session = ctx.get('sessions').create('paired-outline')
        for event in inputs['events']:
            session.append(event['type'], event['data'], surface_op=event.get('surfaceOp'))
            rows['outline'].append(registry.snapshot(session))
        first, subset = session.snapshotEvents(), session.snapshotEvents(0, 1)
        rows['indexed'] = dict(cached=first is session.snapshotEvents(), first=session.eventAt(0),
            absent=session.eventAt(session.seq) is UNDEFINED, range=session.snapshotEvents(1, 3))
        try:
            first.append({})
            rows['indexed']['frozen'] = False
        except TypeError:
            rows['indexed']['frozen'] = True
        session.append('probe/mark', {})
        rows['indexed']['stable'] = len(first) == len(inputs['events']) and len(subset) == 1
        prompt = ctx.get('systemPrompt')
        rows['orders'].update((name, prompt.getSectionOrder(name)) for name in inputs['sectionNames'])
        rows['orders'].update((name, prompt.getContextOrder(name)) for name in inputs['contextNames'])
        rows['checkpoint'] = registry.checkpoint(session)
        registry.register(dict(key='lineageProbe', stateVersion=1, stateSchema=lambda value: value,
            init=lambda _header, cut: dict(cut=cut, own=[]),
            apply=lambda state, event: state if event['seq'] < state['cut'] else dict(cut=state['cut'], own=state['own'] + [event['seq']]),
            wire=dict(view=lambda state: state, viewSchema=lambda value: value)))
        child = Session.fromRestore('lineage-child', inputs['lineage'][1]['seed'],
                               dict(inputs['lineage'][1]['header'], id='lineage-child'), 2, 'detached')
        checkpoint = registry.checkpoint(child)
        child.append('probe/owned', {})
        rows['projectionLineage'] = dict(initial=checkpoint['lineageProbe'],
            full=registry.restore({}, child.snapshotEvents(), 0, child.header, child.inheritedEventCount),
            tail=registry.restore(checkpoint, child.snapshotEvents(4), 4, child.header, child.inheritedEventCount))
    finally:
        await ctx.fiber.dispose()
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT / 'reference')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--runtime', action='store_true')
    options = parser.parse_args()
    if options.runtime:
        inputs = json.loads(options.inputs.read_text(encoding='utf-8'))
        report = observe_runtime(inputs, options.root.resolve(), hashlib.sha256(options.inputs.read_bytes()).hexdigest())
        options.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        return 0
    source, output = options.source_root.resolve(), options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status='runner-error', pin=PIN, scope='Bounded current Source/runtime observations. Retained chunkDecode probes released-v1 migration decoding; chunkPack probes current AssistantStreamAccumulator using all original batch inputs. Current v3 Session, JSONL and persona orders; no automatic acceptance.')
    try:
        actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], encoding='utf-8').strip()
        if actual != PIN:
            raise ValueError('Source differs from the pinned rc1 candidate')
        workspace = output / 'workspace'
        for directory in ('src', 'lib', 'dist', '.git', '.venv', '..source', 'space dir'):
            (workspace / directory).mkdir(parents=True)
        for filename in ('src/中文 name.py', 'src/alpha.py', 'src/f😀p.py', 'src/fxxp.py', 'lib/alpha.py', 'dist/alpha.py', '.git/a', '.venv/a', '.hidden.py', 'file😀.py', '..source/inside.py', 'space dir/a.txt'):
            (workspace / filename).write_text('PRIVATE_BODY_NOT_A_CANDIDATE', encoding='utf-8')
        from dsh.core.system_prompt.current import FIRST_PARTY_SECTION_ORDER
        inputs = dict(workspace=str(workspace), clock=1770000000000,
            searchConfigs=[dict(maxResults=1.0, maxEntries=2.0), dict(maxResults=0), dict(maxEntries=True),
                dict(maxResults=1.5), dict(excludedDirectories=['nested/path'])],
            queries=['', 'src/', 'src\\', 'py', 'ap', 'fp', '中文', '.hidden', '../', '..source/', 'space dir/', '😀'],
            tokens=[dict(line=text, cursor=cursor) for text, cursor in [
                ('@src', 4), ('mail@example', 12), ('😀 @src tail', 7), ('@"space dir/', 12),
                ('\ufeff@中文', 4), ('x\u0085@a', 4), ('@😀', 2), ('@a', -1)]],
            mentions=[dict(candidate=dict(path=path, kind=kind), quote=quote) for path, kind, quote in [
                ('src', 'directory', False), ('space dir', 'directory', False), ('中文 name.py', 'file', False),
                ('plain.py', 'file', True), ('bad".py', 'file', False), ('a\ufeffb', 'file', False)]],
            positions=['0', '1', '1.0', '9007199254740991', '-0', '-1', '1.5', 'true', 'null', '"0"', 'NaN', 'Infinity', '9007199254740992'],
            sectionNames=list(FIRST_PARTY_SECTION_ORDER), contextNames=['SANDBOX_POLICY', 'APPROVAL_POLICY', 'SUBAGENT_DELEGATION'], events=[])
        base = [dict(type='turn/start', seq=0, time=1, data=dict(turn=1)),
                dict(type='turn/end', seq=1, time=2, data=dict(turn=1, reason=dict(kind='completed')))]
        suffix = base + [dict(type='session/end-seed', seq=2, time=3, data={}),
                        dict(type='probe/context', seq=3, time=4, data=dict(provider='provider', model='model'))]
        meta = dict(version=3, id='child', createdAt=1, isSeeded=True)
        inputs['lineage'] = [dict(header=meta, seed=base, cut='2'), dict(header=meta, seed=suffix, cut='2'),
            dict(header=meta, seed=suffix, cut='2', mode='restore'), dict(header=meta, seed=[], cut='0'),
            dict(header=dict(meta, isSeeded=False), seed=[], cut='0'), dict(header=meta, cut='0'),
            dict(header=meta, seed=[]), dict(header=dict(meta, isSeeded=False), seed=[], cut='1'),
            dict(header=meta, seed=[], cut='1')]
        inputs['lineage'] += [dict(header=meta, seed=[], cut=cut) for cut in ['-0', '-1', '1.5', 'true', '"1"', 'NaN', 'Infinity', '9007199254740992', 'null']]
        optional = dict(type='future/optional', seq=0, time=1, data=dict(info='future'))
        inputs['lineage'] += [dict(header=meta, seed=[dict(optional, ignorable=flag)], cut='0')
                              for flag in [True, False, None, 0, 1, 'true']]
        inputs['storageLineage'] = [dict(header=meta, cut='0'), dict(header=meta, cut='2.0'),
            dict(header=dict(meta, isSeeded=False)), dict(header=meta),
            dict(header=dict(meta, isSeeded=False), cut='1')]
        physical = dict(type='session', version=3, id='child', createdAt=1, isSeeded=False, delegationDepth=0)
        inputs['storageLineage'] += [dict(physical=dict(physical, seedLength=cut)) for cut in [0, 2, -1, 0.5, True, None, '1', 9007199254740992]]
        inputs['storageLineage'] += [dict(physical=dict(physical, sandboxMode=None)),
            dict(physical=dict(version=1, id='future', seedLength='invalid'))]
        inputs['strictHeaders'] = [meta, dict(meta, isSeeded=False), dict(version=3, id='child', createdAt=1),
            dict(meta, isSeeded=1), dict(meta, seedLength=0), dict(meta, seedLength='UNDEFINED')]
        def add(kind, data):
            if kind == 'user/message':
                data = dict(data, role='user', id='user-'+str(len(inputs['events'])))
            elif kind == 'assistant/message':
                data = dict(data, turn=1, step=1, stream=[])
                data['message'].update(id='assistant-'+str(len(inputs['events'])), source=dict(kind='model', provider='fixture', model='fixture'))
            row = dict(type=kind, data=data)
            if kind in ('user/message', 'assistant/message'):
                row['surfaceOp'] = 'append'
            inputs['events'].append(row)
        add('turn/start', dict(turn=1))
        add('user/message', dict(source=dict(kind='plugin', plugin='fixture'), content=[dict(type='text', text='not human')]))
        add('user/message', dict(source=dict(kind='user'), content=[dict(type='text', text='😀' * 25)]))
        add('user/message', dict(source=dict(kind='user'), content=[dict(type='text', text='steer')]))
        for text in ('draft', '  final\n reply\ufeff '):
            add('assistant/message', dict(message=dict(role='assistant', content=[dict(type='text', text=text)])))
        add('turn/end', dict(turn=1))
        add('turn/start', dict(turn=1))
        add('turn/start', dict(turn=2))
        add('user/message', dict(source=dict(kind='user'), content=[dict(type='text', text=' ' * 10000)]))
        add('turn/end', dict(turn=2))
        input_path = output / 'inputs.json'
        def chunk_record(count):
            return dict(type='text-chunks', seq0=0, time0=1,
                        data=dict(turn=1, step=1, index=0, texts=['x'] * count, dt=[1] * max(0, count - 1)))
        inputs['chunkRecords'] = [chunk_record(count) for count in (1, 2, 3, 1025)]
        inputs['chunkRecords'] += [dict(chunk_record(2), seq0=-0.0), dict(type='future', seq=-1),
            dict(type='future', seq=-0.0), dict(type='future', seq=0.5), dict(type='future', seq=True)]
        def chunks(count):
            return [dict(type='assistant/chunk', seq=seq, time=seq + 1,
                         data=dict(turn=1, step=1, chunk=dict(type='text-delta', index=0, text='x')))
                    for seq in range(count)]
        inputs['chunkBatches'] = [chunks(count) for count in (2, 3, 1025)]
        inputs['chunkBatches'].append([dict(event, seq=float(event['seq']), time=float(event['time'])) for event in chunks(3)])
        schedule = dict(id='schedule-1', kind='after', prompt='paired reminder', afterSeconds=60,
                        scheduledAt='2026-10-15T00:01:00.000Z')
        state = dict(inheritedEventCount=0, active=[schedule], seenIds=['schedule-1'])
        inputs['scheduleStates'] = [state, dict(state, inheritedEventCount=-0.0), dict(state, extra=True),
            dict(state, seenIds=[]), dict(state, seenIds=['schedule-1', 'schedule-1']), dict(state, active=[schedule, schedule])]
        inputs['scheduleEvents'] = [dict(type='schedule/change', seq=0,
            data=dict(version=1, operation='create', schedule=dict(schedule, id='inherited'))),
            dict(type='schedule/change', seq=1, data=dict(version=1, operation='create', schedule=schedule)),
            dict(type='schedule/change', seq=2, data=dict(version=1, operation='delete', id='schedule-1'))]
        retry = dict(provider='provider', policyKey='policy', retryId='retry-1', retry=1)
        inputs['retryEvents'] = [dict(type='step/start', data={}), dict(type='llm/retry', data=retry),
            dict(type='llm/retry', data=retry), dict(type='llm/retry', data=dict(retry, provider='provider\u0000x')),
            dict(type='step/start', data={}), dict(type='llm/retry', data=retry), dict(type='turn/end', data={})]
        state = dict(openTurnStartSeq=None, lastStepStartSeq=None, lastStepBoundary=None, lastTurn=0)
        inputs['boundaryStates'] = [state, dict(state, ignored='strip'),
            dict(state, lastStepBoundary=dict(kind='start', seq=0, ignored='strip')),
            dict(state, lastTurn=-0.0), dict(state, openTurnStartSeq=-0.0),
            dict(state, lastTurn=True), dict(state, lastTurn=-1), dict(state, lastTurn=0.5),
            dict(state, lastStepBoundary=dict(kind='invalid', seq=0)),
            dict(state, lastStepBoundary=dict(kind='end', seq=2)),
            dict(state, lastTurn=9007199254740992), dict(lastTurn=1)]
        inputs['boundaryEvents'] = [dict(type=kind, seq=seq, data=dict(turn=turn)) for seq, kind, turn in
            [(0, 'turn/start', 1), (1, 'step/start', 1), (2, 'step/end', 1), (3, 'turn/end', 1),
             (4, 'turn/start', 2), (5, 'probe/ignored', 2)]]
        input_path.write_text(json.dumps(inputs, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
        environment = dict(os.environ, TSX_TSCONFIG_PATH=str(source / 'tsconfig.json'))
        frozen = source_inputs(source)
        (output / 'source-inputs.json').write_text(json.dumps(frozen, indent=2) + '\n', encoding='utf-8')
        command = ['node', '--import', (source / 'node_modules/tsx/dist/esm/index.mjs').as_uri(),
            str(ROOT / 'scripts/oracles/rc1_capabilities.mts'), str(source), str(input_path), str(output / 'source.json')]
        run = subprocess.run(command, cwd=str(source), env=environment, capture_output=True, timeout=60)
        (output / 'source.log').write_bytes(run.stdout + run.stderr)
        report['command'], report['exit_code'] = command, run.returncode
        if run.returncode:
            raise RuntimeError('Source observer failed; see source.log')
        source_rows = json.loads((output / 'source.json').read_text(encoding='utf-8'))
        if source_inputs(source) != frozen:
            raise ValueError('Source or compiled library inputs changed during observation')
        expected_hash = hashlib.sha256(input_path.read_bytes()).hexdigest()
        if source_rows['pin'] != PIN or source_rows['inputSha256'] != expected_hash:
            raise ValueError('Source identity or input digest differs')
        command = [options.python, '-I', str(Path(__file__).resolve()), '--runtime', '--root', str(options.root.resolve()),
                   '--inputs', str(input_path), '--output', str(output / 'native.json')]
        run = subprocess.run(command, capture_output=True, timeout=60)
        (output / 'native.log').write_bytes(run.stdout + run.stderr)
        if run.returncode:
            raise RuntimeError('Native observer failed; see native.log')
        native_report = json.loads((output / 'native.json').read_text(encoding='utf-8'))
        native_rows = native_report['observations']
        validate_runtime(native_report, options.root.resolve(), digest(source_rows['observations']), expected_hash)
        report['native_runtime'] = native_report
        report['source_inputs_sha256'] = hashlib.sha256((output / 'source-inputs.json').read_bytes()).hexdigest()
        report['input_sha256'] = expected_hash
        report['observer_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('scripts/rc1_capabilities_oracle.py', 'scripts/oracles/rc1_capabilities.mts')}
        report['cases'] = [dict(name=name, matched=value == native_rows.get(name)) for name, value in source_rows['observations'].items()]
        if set(source_rows['observations']) != REQUIRED or set(native_rows) != REQUIRED:
            raise ValueError('Incomplete or unexpected observation categories')
        report['status'] = 'matched' if all(row['matched'] for row in report['cases']) else 'different'
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as error:
        report['error'] = str(error)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'pin', 'cases', 'error') if key in report}, ensure_ascii=True))
    return {'matched': 0, 'different': 1, 'runner-error': 2}[report['status']]


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
