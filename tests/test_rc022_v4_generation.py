import pytest

from scripts.rc022_v4_generation_probe import observe


@pytest.mark.asyncio
async def test_v4_generation_verifies_real_files_and_publishes_with_fresh_worker(tmp_path):
    rows=await observe(tmp_path/'native')
    for row in rows:
        name=row['name']
        if name.startswith('publish-'):
            assert row.get('published') and row.get('verified') and row['target'] and row['sourceUnchanged'] and row['stages']==0,row
        elif name in ('valid','lifecycle','empty','plugin','opaque-unknown','prefix-append'):
            assert row['direct']==dict(bytes=True,digest=True),row
            if 'worker' in row:assert row['worker']==row['direct']
        else:
            assert isinstance(row['direct'],str),row
            if 'worker' in row:assert row['worker']==row['direct']
    for compression in ('none','zstd'):
        by_name={row['name']:row for row in rows if row['compression']==compression}
        assert 'torn physical tail' in by_name['torn-line']['direct']
        assert 'does not exist' in by_name['invalid-image']['direct']
        assert 'unresolved tool call' in by_name['unresolved-tool']['direct']
        assert 'embedded stream' in by_name['bad-stream']['direct']
