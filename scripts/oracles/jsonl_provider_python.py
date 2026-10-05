import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import platform
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--directory', type=Path, required=True)
parser.add_argument('--inputs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
ROOT = arguments.root.resolve()
sys.path.insert(0, str(ROOT))

from dsh.cordis import Context
from dsh.core.session import SessionPlugin
from dsh.session.sqlite_logical import header_from_stored, logical_numbers
from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistencePlugin
from dsh.session import jsonl_store
from dsh.session.jsonl_zstd import compress_frame, decompress_frame, scan_frames
from dsh.session.jsonl_format import parse_header_meta, scan_log
from dsh.cordis.json_text import stringify_json


def sha(data):
    return hashlib.sha256(data).hexdigest()


def observed(operation):
    try:
        return dict(value=operation())
    except Exception as error:
        return dict(error=str(error))


def frames(directory, source):
    rows = []
    cross = []
    for expected in source['rows']:
        fields = expected['id'].split('/')
        if fields[0] == 'frame':
            plaintext = (directory / ('plain-' + fields[1] + '.bin')).read_bytes()
            frame = (directory / ('frame-' + fields[1] + '.bin')).read_bytes()
            encoded = compress_frame(plaintext)
            (directory / ('native-frame-' + fields[1] + '.bin')).write_bytes(encoded)
            row = dict(encoded=sha(encoded), decoded=sha(decompress_frame(frame)), scan=scan_frames(frame))
            cross.append(dict(id='cross-frame/' + fields[1], decoded=sha(plaintext), scan=scan_frames(encoded)))
        elif fields[0] == 'cut':
            frame = (directory / ('frame-' + fields[1] + '.bin')).read_bytes()[:int(fields[2])]
            try:
                prefix = dict(sha256=sha(decompress_frame(frame, incomplete=True)))
            except Exception as error:
                prefix = dict(error=getattr(error, 'code', type(error).__name__))
            row = dict(scan=observed(lambda: scan_frames(frame)), prefix=prefix)
        elif fields[0] == 'checksum':
            frame = bytearray((directory / ('frame-' + fields[1] + '.bin')).read_bytes())
            frame[-1] ^= 1
            try:
                decompress_frame(bytes(frame))
                failure = None
            except Exception as error:
                failure = getattr(error, 'code', type(error).__name__)
            row = dict(failure=failure)
        elif fields[0] == 'descriptor':
            frame = bytes([0x28, 0xb5, 0x2f, 0xfd, int(fields[1])]) + bytes(30)
            row = dict(scan=observed(lambda: scan_frames(frame)))
        else:
            raise ValueError('Unexpected JSONL frame fixture')
        rows.append(dict(row, id=expected['id']))
    return rows, cross


async def mount(root, item):
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(JsonlSessionPersistencePlugin, dict(root=str(root), compression=item['compression'], packChunks=item['packChunks']))
    return context, context.get('sessionPersistence')


def metadata_detached(value):
    if hasattr(value, 'to_dict'):
        return metadata_detached(value.to_dict())
    if hasattr(value, 'meta') and hasattr(value, 'events'):
        return dict(meta=metadata_detached(value.meta), events=metadata_detached(value.events))
    if isinstance(value, dict):
        return {name: metadata_detached(item) for name, item in value.items() if name != 'revision'}
    if isinstance(value, list):
        return [metadata_detached(item) for item in value]
    return value


def metadata_value(value, root=None):
    encoded = stringify_json(dict(value=metadata_detached(value)))
    if root is not None:
        encoded = encoded.replace(str(root).replace('\\', '\\\\'), '<root>')
    return json.loads(encoded)


def metadata_error(error, root=None):
    message = str(error)
    if root is not None:
        message = message.replace(str(root), '<root>')
    failure = dict(name=getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error'), message=message)
    if getattr(error, 'location', None) is not None:
        failure['location'] = error.location.to_dict()
        failure['location']['path'] = failure['location']['path'].replace(str(root), '<root>')
    return dict(error=failure)


def metadata_format_observed(operation):
    try:
        return metadata_value(operation())
    except Exception as error:
        return metadata_error(error)


async def metadata_rows(directory, fixtures):
    rows = []
    for index, item in enumerate(fixtures):
        identity, line = item['id'], item['line']
        rows.append(dict(id='metadata-format/' + identity,
            metadata=metadata_format_observed(lambda: parse_header_meta(line)),
            scan=metadata_format_observed(lambda: scan_log((line + '\n').encode('utf-8')))))
        for compression in ('zstd', 'none'):
            relative = Path(compression) / str(index) / '_no-cwd/raw' / (
                'session.jsonl.zstd' if compression == 'zstd' else 'session.jsonl')
            encoded = (directory / 'source-metadata' / relative).read_bytes()
            root = directory / 'native-metadata' / compression / str(index)
            path = directory / 'native-metadata' / relative
            path.parent.mkdir(parents=True)
            path.write_bytes(encoded)
            context, provider = await mount(root, dict(compression=compression, packChunks=True))
            operations = [
                ('stored', lambda: provider.loadStored('raw')),
                ('raw', lambda: provider.read_raw('raw')),
                ('list', lambda: provider.list()),
                ('suffix', lambda: provider.read_from('raw', 0)),
                ('inspect', lambda: provider.inspect('raw')),
            ]
            try:
                for name, operation in operations:
                    try:
                        observation = metadata_value(await operation(), root)
                    except Exception as error:
                        observation = metadata_error(error, root)
                    rows.append(dict(id='metadata-public/' + compression + '/' + identity + '/' + name,
                        observation=observation, artifactSha256=sha(encoded), unchanged=path.read_bytes() == encoded))
            finally:
                await context.fiber.dispose()
            if path.read_bytes() != encoded:
                raise ValueError('Metadata observation changed the source artifact')
    return rows


async def main():
    directory = arguments.directory.resolve()
    inputs = json.loads(arguments.inputs.read_text(encoding='utf-8'))
    if any(sha((directory / name).read_bytes()) != expected for name, expected in inputs['generated'].items()):
        raise ValueError('Generated JSONL Source fixtures differ')
    original = json.loads((directory / 'source-produce.json').read_text(encoding='utf-8'))
    fixtures = [{key: item[key] for key in ('key', 'compression', 'packChunks', 'metadata', 'events')} for item in original['inputs']]
    if fixtures != inputs['providerFixtures']:
        raise ValueError('Generated JSONL provider fixtures differ')
    metadata = json.loads((directory / 'source-metadata.json').read_text(encoding='utf-8'))
    if metadata['inputs'] != inputs['metadataFixtures']:
        raise ValueError('Generated JSONL metadata fixtures differ')
    source_frames = json.loads((directory / 'frames/source.json').read_text(encoding='utf-8'))
    rows, cross = frames(directory / 'frames', source_frames)
    materialized, mutual, revisions = [], [], {}
    for item in original['inputs']:
        root = directory / ('native-' + item['key'])
        context, provider = await mount(root, item)
        metadata = header_from_stored(item['metadata'])
        events = item['events']
        try:
            lazy = not root.exists()
            await provider.create(metadata)
            detached = not root.exists()
            await provider.append(metadata.id, events[:3])
            path = Path(provider.locate(metadata).path)
            prior = path.read_bytes()
            await provider.append(metadata.id, events[3:])
            appended = path.read_bytes()
            materialized.append(dict(id='materialization/' + item['key'], lazy=lazy, detached=detached,
                retained=appended[:len(prior)] == prior, sha256=sha(appended), relative=path.relative_to(root).as_posix()))
            revisions[item['key']] = await provider.stored_revision(metadata.id)
        finally:
            await context.fiber.dispose()
        context, provider = await mount(directory / ('source-' + item['key']), item)
        try:
            if await provider.stored_revision(metadata.id) != item['revision']:
                raise AssertionError('Cross-file full filesystem revision differs')
            loaded = await provider.load(metadata.id)
            inspected = await provider.inspect(metadata.id)
            suffix = await provider.read_from(metadata.id, 2)
            raw = await provider.read_raw(metadata.id)
            prepared = await provider.prepare(metadata.id)
            try:
                mutual.append(dict(id='mutual/' + item['key'], meta=loaded.meta.to_dict(), events=loaded.events,
                    inspected=len(inspected.events), suffix=suffix.events, raw=raw['content'], filename=raw['filename'],
                    prepared=len(prepared.session.events), endSeed=prepared.session.events[-1]['type'],
                    unpublished=context.get('sessions').get(metadata.id) is None, revisionMatched=True))
            finally:
                prepared.dispose()
        finally:
            await context.fiber.dispose()
    rows.extend(materialized + mutual + cross)
    rows.extend(await metadata_rows(directory, inputs['metadataFixtures']))
    (directory / 'native-revisions.json').write_text(json.dumps(revisions), encoding='utf-8')
    if any(sha((directory / name).read_bytes()) != expected for name, expected in inputs['generated'].items()):
        raise ValueError('Generated JSONL Source fixtures changed during observation')
    report = dict(root=str(ROOT), python=platform.python_version(), moduleFile=jsonl_store.__file__,
        modules={name: sha((ROOT / name).read_bytes()) for name in inputs['modules']},
        assets={name: sha((ROOT / name).read_bytes()) for name in inputs['assets']},
        generatedInputsSha256=sha(arguments.inputs.read_bytes()), rows=logical_numbers(rows))
    arguments.output.write_text(json.dumps(report, ensure_ascii=True), encoding='utf-8')


asyncio.run(main())
