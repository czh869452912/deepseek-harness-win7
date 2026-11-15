from types import SimpleNamespace as NS

import pytest

from dsh.core.abort import AbortController
from dsh.context.agent_instructions import files_authorized as files, config_authorized as config


@pytest.mark.asyncio
async def test_actual_host_provider_scopes_and_source_bounds(tmp_path):
    from scripts.rc022_instruction_files_probe import observe
    rows = {row['name']:row for row in await observe(tmp_path)}
    host, provider = rows['host-load']['value'], rows['provider-load']['value']
    assert len(host['observed']) == len(provider['observed']) == 6
    assert len(host['deduped']) == len(provider['deduped']) == 2
    assert host['observed'][1]['content'].startswith('\ufeff')
    assert not provider['observed'][1]['content'].startswith('\ufeff')
    assert [file['displayPath'] for file in host['included']] == ['$DSH_HOME/AGENTS.md', 'AGENTS.md', 'AGENTS.local.md', 'child\\AGENTS.md']
    assert rows['scope-collision']['value']['file']['displayPath'] == '.\\agents-global\\AGENTS.md'
    assert rows['scope-missing']['value'] == dict(kind='absent')
    assert all(file['displayPath'] != 'child\\AGENTS.md' for file in rows['oversized-source']['value']['observed'])
    assert rows['empty']['value'] is rows['disabled']['value'] is None
    assert rows['empty-replacement']['value']['included'] == []
    assert 'No workspace instructions are currently active.' in rows['empty-replacement']['value']['rendered']['text']
    assert rows['provider-bom']['text'] == rows['provider-bom']['stream'] == '\ufeffvalue'
    assert rows['provider-bom']['bytes'] == list('\ufeffchanged'.encode('utf-8'))


@pytest.mark.asyncio
async def test_stream_limit_closes_source_and_never_pulls_unneeded_chunk():
    seen=[]
    async def stream(target, signal):
        async def chunks():
            try:
                seen.append(1);yield 'abc'
                seen.append(2);yield '😀'
                seen.append(3);yield 'unneeded'
            finally:seen.append('closed')
        return chunks()
    filesystem = NS(streamText=stream)
    assert await files.read_bounded(dict(absolutePath='unused', target=object()), 6, filesystem) is None
    assert seen == [1, 2, 'closed']
    seen.clear()
    assert await files.read_bounded(dict(absolutePath='unused', target=object(), size=7), 6, filesystem) is None
    assert seen == []


@pytest.mark.asyncio
async def test_read_limit_cleanup_failure_is_unavailable_without_masking_cancellation():
    closed=[]
    async def stream(target, signal):
        async def chunks():
            try:yield 'oversized'
            finally:
                closed.append(True)
                raise RuntimeError('stream close failed')
        return chunks()
    filesystem=NS(streamText=stream)
    assert await files.read_bounded(dict(absolutePath='unused',target=object()), 1, filesystem) is None
    assert closed == [True]


@pytest.mark.asyncio
async def test_scope_missing_and_unavailable_are_distinct_and_cancellation_preserves_reason(tmp_path):
    resolved=config.resolve_discovery_config(dict(dshHome=str(tmp_path), agentsHome=str(tmp_path)))
    controller=AbortController();failure=RuntimeError('metadata unavailable')
    async def resolve(path, options):return path
    async def missing(target, signal):return None
    filesystem=NS(resolve=resolve,stat=missing)
    assert await files.probe_scope_instruction('.\0AGENTS.md', str(tmp_path), resolved, filesystem, controller.signal) == dict(kind='absent')
    async def unavailable(target, signal):raise failure
    filesystem.stat=unavailable
    assert await files.probe_scope_instruction('.\0AGENTS.md', str(tmp_path), resolved, filesystem, controller.signal) == dict(kind='unavailable')
    with pytest.raises(RuntimeError) as caught:await files.find_project_root(str(tmp_path), ['.git'], filesystem, controller.signal)
    assert caught.value is failure
    controller.abort(failure)
    with pytest.raises(RuntimeError) as caught:await files.probe_scope_instruction('.\0AGENTS.md', str(tmp_path), resolved, filesystem, controller.signal)
    assert caught.value is failure


@pytest.mark.asyncio
async def test_bom_decode_across_single_byte_chunks_and_edit(tmp_path, monkeypatch):
    import dsh.fs.fs_local as local
    monkeypatch.setattr(local, 'READ_CHUNK_BYTES', 1)
    path=tmp_path/'bom.txt';path.write_bytes(b'\xef\xbb\xbf\xef\xbb\xbfhello')
    filesystem=local.FsService(cwd=str(tmp_path));target=await filesystem.resolve('bom.txt')
    assert await filesystem.readText(target) == '\ufeffhello'
    assert ''.join([chunk async for chunk in await filesystem.streamText(target)]) == '\ufeffhello'
    result=await filesystem.editText(target,dict(oldString='hello',newString='world'))
    assert result.before == '\ufeffhello' and path.read_bytes() == '\ufeffworld'.encode('utf-8')
