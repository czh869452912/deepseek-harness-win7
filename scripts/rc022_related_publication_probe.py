"""Pair real child revision witnesses at parent preparation and publication."""
import asyncio
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe

OUTPUT = None
CASES = [dict(name=name, compression=compression) for compression in ('none', 'zstd')
         for name in ('stable', 'before-prepare', 'after-prepare', 'during-verify',
                      'at-source-check', 'deleted', 'cancel-after-prepare', 'concurrent', 'retry-failure')]


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text(json.dumps(CASES), encoding='utf-8')
    return [path]


def migration_adapter(children):
    # Explicit candidate format library, independent of installed V3 Session.
    # The verifier below observes physical publication, not installed admission.
    from dsh.session.format import createSessionFormatCatalog
    from dsh.session.format_v0_to_v1 import releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, sessionFormatV0ToV1
    from dsh.session.format_v1_to_v2 import releasedV2SessionFormatCodec, sessionFormatV1ToV2
    from dsh.session.format_v2_to_v3 import releasedV3SessionFormatCodec, sessionFormatV2ToV3
    from dsh.session.format_v3_to_v4 import (releasedV4SessionFormatCodec, createSessionFormatV3ToV4,
        restoreReleasedV4Artifact, assertReleasedV4Header, RELEASED_V3_EVENT_TYPES)
    known = set(RELEASED_V3_EVENT_TYPES) | {'developer/message'}
    catalog = createSessionFormatCatalog(dict(currentVersion=4,
        codecs=[releasedV0SessionFormatCodec, releasedV1SessionFormatCodec, releasedV2SessionFormatCodec, releasedV3SessionFormatCodec, releasedV4SessionFormatCodec],
        currentEncoder=releasedV4SessionFormatCodec,
        migrations=[sessionFormatV0ToV1, sessionFormatV1ToV2, sessionFormatV2ToV3, createSessionFormatV3ToV4(children)],
        restoreCurrent=lambda artifact: restoreReleasedV4Artifact(artifact, known),
        restoreTransformedCurrent=lambda artifact: restoreReleasedV4Artifact(artifact, known),
        restoreCurrentHeader=lambda header: (assertReleasedV4Header(header), header)[1]))
    return dict(currentVersion=4,
        createRestore=lambda header: catalog.createRestore(header, dict(recovery='recoverable', validation='transformed')),
        encodeHeader=catalog.encodeCurrentHeader, encodeEvent=catalog.encodeCurrentEvent)


async def observe(workspace):
    from dsh.core.abort import AbortController
    from dsh.session.catalog_migration import prepareCatalogFacts
    from dsh.session.generation import createJsonlGenerationRuntime
    from dsh.session.file_revision import filesystem_identity
    from dsh.session.jsonl_current import generationLogFilename
    from dsh.session.jsonl_zstd import compress_frame
    results = []
    for row in CASES:
        name, compression = row['name'], row['compression']
        root = workspace/(compression+'-'+name)
        child = root/'child'
        child.mkdir(parents=True)
        header = dict(version=3, id='parent', createdAt=1, isSeeded=False, delegationDepth=0)
        child_header = dict(header, id='child', createdAt=2, delegationDepth=1, parentSession='parent', origin='subagent')
        def encode(value):
            raw = (json.dumps(dict(type='session', **value), separators=(',', ':'))+'\n').encode('utf-8')
            return raw if compression == 'none' else compress_frame(raw)
        source = root/generationLogFilename(3, compression)
        target = root/generationLogFilename(4, compression)
        child_path = child/source.name
        original = encode(header)
        source.write_bytes(original)
        child_path.write_bytes(encode(child_header))
        facts = await prepareCatalogFacts('parent', [dict(path=str(child_path), header=child_header)], compression, None)
        calls = []
        def mutate():
            if name == 'deleted':
                child_path.unlink()
            else:
                with child_path.open('ab') as file:
                    file.write(b'changed')
        async def validate():
            calls.append('related')
            await asyncio.sleep(0)
            await facts.validate()
        async def verify(path, encoding, expected_id, count, prefix=None):
            calls.append('verify')
            data = Path(path).read_bytes()
            if name == 'during-verify':
                mutate()
            size = len(data) if prefix is None else prefix['bytes']
            return dict(identity=filesystem_identity(path), bytes=size, digest=hashlib.sha256(data[:size]).hexdigest())
        async def barrier(phase, attempt):
            calls.append(phase)
            if phase == 'before-source-check' and name == 'at-source-check':
                mutate()
        runtime = createJsonlGenerationRuntime(dict(barrier=barrier))
        controller = AbortController()
        result = dict(name=name, compression=compression)
        def failure(error):
            return 'missing' if isinstance(error, FileNotFoundError) else getattr(error, 'name', type(error).__name__)
        try:
            if name == 'before-prepare':
                mutate()
            prepared = await runtime.prepare(dict(sourcePath=str(source), sourceVersion=3,
                currentPath=str(target), compression=compression, format=migration_adapter(facts.facts),
                validateRelatedSources=validate, verifyCurrentFile=verify, signal=controller.signal))
            result['prepared'] = prepared.artifact['header']['version']
            if name in ('after-prepare', 'deleted', 'retry-failure'):
                mutate()
            if name == 'cancel-after-prepare':
                controller.abort(RuntimeError('load cancelled'))
            try:
                if name == 'concurrent':
                    first, second = await asyncio.gather(prepared.publish(), prepared.publish())
                    result['samePublication'] = first is second
                else:
                    await prepared.publish()
                result['published'] = True
            except Exception as error:
                result['error'] = failure(error)
                if name == 'retry-failure':
                    try:
                        await prepared.publish()
                    except Exception as repeated:
                        result['sameFailure'] = repeated is error
        except Exception as error:
            result['error'] = failure(error)
        result.update(calls=calls, target=target.exists(), sourceUnchanged=source.read_bytes() == original,
                      stages=len(list(root.glob('*.tmp'))), children=facts.facts[0]['descriptorCount'])
        results.append(result)
    return results


async def native():
    return await observe(OUTPUT/'files/native')


if __name__ == '__main__':
    probe.native = native
    probe.main('rc022_related_publication.mts',
        'Real parent V3-to-V4 staging with original child revision witnesses, async validation before preparation and again before publication. Byte verifier injected on both sides; installed V4 Session acceptance remains separate.',
        [Path(__file__).resolve(), ROOT/'dsh/session/generation.py', ROOT/'dsh/session/catalog_migration.py',
         ROOT/'reference/packages/session/session-persistence-jsonl/src/generation.ts'], prepare)
