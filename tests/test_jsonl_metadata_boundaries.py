import json

import pytest

from dsh.cordis import Context
from dsh.core.session import SessionPlugin
from dsh.session.jsonl_format import parse_header_meta, header_bytes
from dsh.session.jsonl_zstd import compress_frame
from dsh.session.persistence import SessionFormatUnsupportedError
from dsh.session.persistence_jsonl_canonical import JsonlSessionPersistencePlugin
from dsh.session.sqlite_logical import SessionPersistenceCorruptionError


async def mounted_artifact(root, compression, line):
    path = root / '_no-cwd/raw' / ('session.jsonl.zstd' if compression == 'zstd' else 'session.jsonl')
    path.parent.mkdir(parents=True)
    content = (line + '\n').encode('utf-8')
    encoded = compress_frame(content) if compression == 'zstd' else content
    path.write_bytes(encoded)
    context = Context()
    await context.plugin(SessionPlugin)
    await context.plugin(JsonlSessionPersistencePlugin, {'root': str(root), 'compression': compression})
    return context, context.get('sessionPersistence'), path, encoded


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['zstd', 'none'])
@pytest.mark.parametrize('field', ['cwd', 'parentSession', 'seedLength'])
async def test_present_null_survives_physical_reads_and_is_refused_at_its_owned_boundary(tmp_path, compression, field):
    line = json.dumps(dict(type='session', id='raw', version=0, createdAt=1, delegationDepth=0, **{field: None}))
    context, provider, path, encoded = await mounted_artifact(tmp_path, compression, line)
    try:
        metadata = parse_header_meta(line)
        assert field in metadata and metadata[field] is None
        assert json.loads(header_bytes(metadata))[field] is None
        raw = await provider.read_raw('raw')
        assert raw['meta'].to_dict()[field] is None
        assert raw['content'] == line + '\n'
        if field == 'cwd':
            for operation in (provider.loadStored, provider.inspect, provider.load):
                with pytest.raises(ValueError, match='header id cannot name a storage path'):
                    await operation('raw')
            with pytest.raises(ValueError, match='header id cannot name a storage path'):
                await provider.list()
        else:
            stored = await provider.loadStored('raw')
            assert set(stored) == {'meta', 'events', 'revision'}
            assert stored['meta'].to_dict()[field] is None
            assert (await provider.read_from('raw', 0)).meta.to_dict()[field] is None
            assert (await provider.list())[0].to_dict()[field] is None
            for operation in (provider.inspect, provider.load, provider.prepare):
                with pytest.raises(SessionPersistenceCorruptionError) as failed:
                    await operation('raw')
                assert failed.value.name == 'SessionPersistenceCorruptionError'
                assert str(failed.value).startswith('stored session "raw" failed validation: Error: session header ' + field)
                assert failed.value.cause is not None
        assert path.read_bytes() == encoded
        assert context.get('sessions').get('raw') is None
    finally:
        await context.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['zstd', 'none'])
@pytest.mark.parametrize('cwd', [False, 1, {}])
async def test_nonstring_cwd_preserves_original_project_identity_refusal(tmp_path, compression, cwd):
    line = json.dumps(dict(type='session', id='raw', version=0, createdAt=1, delegationDepth=0, cwd=cwd))
    context, provider, path, encoded = await mounted_artifact(tmp_path, compression, line)
    try:
        with pytest.raises(ValueError) as failed:
            await provider.loadStored('raw')
        assert str(failed.value) == 'corrupt session log "%s": header id "raw" and cwd identify "%s"' % (
            path, tmp_path / '--root--/raw' / path.name)
        assert path.read_bytes() == encoded
    finally:
        await context.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['zstd', 'none'])
@pytest.mark.parametrize('version', ['-1', '1', '0.5', '1e999'])
async def test_unsupported_format_retains_public_name_and_actual_raw_location(tmp_path, compression, version):
    line = '{"type":"session","id":"raw","version":%s,"createdAt":1,"delegationDepth":0}' % version
    context, provider, path, encoded = await mounted_artifact(tmp_path, compression, line)
    try:
        with pytest.raises(SessionFormatUnsupportedError) as failed:
            await provider.inspect('raw')
        assert failed.value.name == 'SessionFormatUnsupportedError'
        assert failed.value.location.kind == 'jsonl'
        assert failed.value.location.path == str(path)
        assert str(failed.value).endswith(' (raw log: %s)' % path)
        assert path.read_bytes() == encoded
    finally:
        await context.fiber.dispose()
