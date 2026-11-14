"""Python import ownership supplements the paired JavaScript Loader journeys."""
import asyncio
import sys

import pytest

from dsh.cordis import Context
from dsh.cordis.loader import Loader


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy_dispose', [False, True])
async def test_shared_file_module_lives_until_last_owner_and_reloads(tmp_path, legacy_dispose):
    path = tmp_path / 'shared_plugin.py'
    template = (
        'from dsh.cordis.plugin import Plugin\n'
        'class Shared(Plugin):\n'
        '    version = {version!r}\n'
        '    def apply(self, ctx):\n'
        '        pass\n'
    )
    path.write_text(template.format(version='first'), encoding='utf-8')
    specifier = str(path) + ':Shared'
    ctx = Context()
    loader = Loader(ctx)
    try:
        first_id = await loader.create(dict(id='first', name=specifier))
        second_id = await loader.create(dict(id='second', name=specifier))
        await loader.await_()
        first, second = loader.resolve(first_id), loader.resolve(second_id)
        name = first._loaded_module_name
        module = sys.modules[name]
        assert second._loaded_module_name == name
        assert first.moduleNamespace is second.moduleNamespace is module.Shared
        assert len(loader._module_owners[name]['owners']) == 2
        if legacy_dispose:
            await first._dispose_async()
        else:
            loader.remove(first_id)
        await asyncio.sleep(0)
        assert sys.modules[name] is module
        assert loader.registry_map[specifier] is module.Shared
        assert second.moduleNamespace.version == 'first'
        loader.remove(second_id)
        await asyncio.sleep(0)
        assert name not in sys.modules
        assert name not in loader._module_owners
        assert specifier not in loader.registry_map
        # A different size avoids timestamp-only pyc reuse on low resolution disks.
        path.write_text(template.format(version='second-longer-version'), encoding='utf-8')
        third_id = await loader.create(dict(id='third', name=specifier))
        await loader.await_()
        third = loader.resolve(third_id)
        assert third.moduleNamespace is not module.Shared
        assert third.moduleNamespace.version == 'second-longer-version'
    finally:
        await ctx.fiber.dispose()
    assert name not in sys.modules
