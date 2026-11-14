"""Real source reads retain revision witnesses without publishing successors."""
import json

import pytest

from dsh.core.abort import AbortController
from dsh.session.catalog_migration import prepareCatalogFacts
from dsh.session.format import SessionFormatError
from dsh.session.format_catalog import historicalSessionFormatCatalog
from dsh.session.generation import JsonlGenerationSourceChangedError, readDecodedJsonlSource
from dsh.session.jsonl_current import generationLogFilename
from dsh.session.jsonl_zstd import compress_frame


def write_child(root, compression, body, version=3):
    header = dict(version=version, id='child', createdAt=2, isSeeded=False, delegationDepth=1,
                  origin='subagent', parentSession='parent')
    physical = dict(type='session', **header)
    if version < 2:
        del physical['isSeeded']
    first = (json.dumps(physical)+'\n').encode('utf-8')
    path = root/generationLogFilename(version, compression)
    path.write_bytes(first+body if compression=='none' else compress_frame(first)+(compress_frame(body) if body else b''))
    return dict(header=header, path=str(path))


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['none', 'zstd'])
@pytest.mark.parametrize('version', [0, 1, 2, 3])
async def test_old_descriptor_defaults_and_revision_witness(tmp_path, compression, version):
    descriptor = dict(type='subagent/descriptor',seq=0,time=2,
                      data=dict(version=1,provider='spawn',label='',agentModel=''))
    source = write_child(tmp_path, compression, (json.dumps(descriptor)+'\n').encode('utf-8'), version)
    prepared = await prepareCatalogFacts('parent', [source], compression, AbortController().signal)
    assert prepared.failures == []
    assert prepared.facts == [dict(childId='child',childCreatedAt=2,descriptorCount=1,
        descriptor=descriptor['data'],sourcePath=source['path'])]
    await prepared.validate()
    assert len(list(tmp_path.iterdir())) == 1
    with open(source['path'],'ab') as stream:
        stream.write(b'changed')
    with pytest.raises(JsonlGenerationSourceChangedError):
        await prepared.validate()


@pytest.mark.asyncio
@pytest.mark.parametrize('compression', ['none', 'zstd'])
async def test_unavailable_child_still_has_witness(tmp_path, compression):
    source = write_child(tmp_path,compression,b'{broken\n'+json.dumps(dict(type='turn/end',seq=1,time=2,data={})).encode('utf-8')+b'\n')
    prepared = await prepareCatalogFacts('parent',[source],compression,AbortController().signal)
    assert prepared.facts[0]['descriptor'] is None
    assert len(prepared.failures) == 1
    assert isinstance(prepared.failures[0]['error'],SessionFormatError)
    await prepared.validate()
    from pathlib import Path
    Path(source['path']).unlink()
    with pytest.raises(FileNotFoundError):
        await prepared.validate()


@pytest.mark.asyncio
async def test_decoded_source_keeps_format_and_io_categories(tmp_path):
    adapter = dict(createRestore=lambda header: historicalSessionFormatCatalog.createRestore(
        header,dict(recovery='recoverable',validation='current')))
    path = str(tmp_path/'missing.jsonl')
    with pytest.raises(FileNotFoundError):
        await readDecodedJsonlSource(path,3,'none',adapter)
    source = write_child(tmp_path,'none',b'')
    with pytest.raises(SessionFormatError,match='Error: resolved JSONL source filename identifies v2, but its header identifies v3') as captured:
        await readDecodedJsonlSource(source['path'],2,'none',adapter)
    assert isinstance(captured.value.cause,ValueError)
    controller = AbortController(); reason = RuntimeError('cancelled child');controller.abort(reason)
    with pytest.raises(RuntimeError) as captured:
        await readDecodedJsonlSource(source['path'],3,'none',adapter,controller.signal)
    assert captured.value is reason
