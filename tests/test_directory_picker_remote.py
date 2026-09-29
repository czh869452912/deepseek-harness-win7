import pytest
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.host.directory_picker.browse import BrowseDirectoryPickerService
from dsh.host.directory_picker.base import DirectoryPickerError
from dsh.api.directory_picker import DirectoryPickerController
from dsh.typert.remote import TypertRemoteFailure


@pytest.mark.asyncio
async def test_browse_bounds_paths_and_errors(tmp_path):
    ctx = Context()
    service = BrowseDirectoryPickerService(ctx, {'maxEntries': 2})
    for name in ['z', 'a', '.hidden']:
        (tmp_path / name).mkdir()
    try:
        listing = await service.list_directory(str(tmp_path))
        assert [row['name'] for row in listing['entries']] == ['.hidden', 'a']
        assert listing['truncated']
        assert listing['crumbs'][-1]['path'] == str(tmp_path)
        with pytest.raises(DirectoryPickerError) as failure:
            await service.list_directory('relative')
        assert failure.value.code == 'directory-unreadable'
        with pytest.raises(DirectoryPickerError):
            await service.create_directory(str(tmp_path), '../outside')
        assert await service.create_directory(str(tmp_path), 'child') == str(tmp_path / 'child')
        with pytest.raises(DirectoryPickerError) as failure:
            await service.create_directory(str(tmp_path), 'child')
        assert failure.value.code == 'directory-exists'
        signal = AbortController()
        signal.abort()
        with pytest.raises(RuntimeError, match='aborted'):
            await service.list_directory(str(tmp_path), signal.signal)
        await ctx.plugin(DirectoryPickerController)
        with pytest.raises(TypertRemoteFailure) as failure:
            await ctx.get('directoryPickerController').pick(signal.signal)
        assert failure.value.failure['code'] == 'directory-picker-unavailable'
    finally:
        await ctx.fiber.dispose()
