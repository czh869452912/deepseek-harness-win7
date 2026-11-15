import errno
import sys

import pytest

from dsh.subprocess.error import SubprocessError,SubprocessExecutableNotFoundError,subprocess_spawn_failure
from scripts.rc022_subprocess_errors_probe import observe


@pytest.mark.asyncio
async def test_canonical_error_hierarchy_identity_and_classification():
    rows=await observe()
    assert len(rows)==12
    assert rows[0]['code']=='SUBPROCESS_SPAWN_NOT_FOUND' and rows[0]['cause']
    assert rows[1]['code']=='SUBPROCESS_SPAWN_FAILED'
    assert all(row['same'] for row in rows[4:11])
    assert rows[-1]['harness'] and rows[-1]['subprocess'] and rows[-1]['cause']


@pytest.mark.parametrize('code,expected',[(errno.ENOENT,'SUBPROCESS_SPAWN_NOT_FOUND'),(errno.EACCES,'SUBPROCESS_SPAWN_FAILED')])
def test_native_oserror_keeps_original_cause(code,expected):
    error=OSError(code,'platform launch failure')
    converted=subprocess_spawn_failure(error,'shell')
    assert converted.code==expected and converted.cause is error


@pytest.mark.asyncio
async def test_real_lookup_miss_uses_canonical_error_subclass():
    from dsh.cordis import Context
    from dsh.subprocess.local_authorized import AuthorizedLocalSubprocessRuntime
    ctx=Context();owner=await ctx.plugin(AuthorizedLocalSubprocessRuntime)
    try:
        with pytest.raises(SubprocessExecutableNotFoundError) as caught:await ctx.subprocess.resolveExecutable('dsh-absent-rc022-executable',dict(PATH=''))
        assert isinstance(caught.value,SubprocessError) and caught.value.code=='SUBPROCESS_EXECUTABLE_NOT_FOUND'
    finally:await owner.dispose();await ctx.fiber.dispose()
