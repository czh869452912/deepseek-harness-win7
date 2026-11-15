import asyncio
from pathlib import Path
import sysconfig

import pytest

from scripts.rc022_hmr_consumers_probe import observe


@pytest.mark.asyncio
async def test_replacements_keep_live_config_injection_and_parent_ownership(tmp_path):
    assert await asyncio.wait_for(observe(tmp_path/'consumers'), 25) == [
        dict(mode='volatile', before=1, activations=2, distinct=True,
             at_reload='current', new='after-reload', old='current'),
        dict(mode='provider', last=['updated', 2, 2], namespace_changed=True),
        dict(mode='children', records=['1:initial', '1:child', '1:independent',
                                      '2:initial', '2:independent'], instances=2),
        dict(mode='removed-traversal', records=['1:initial'], replacement_active=False,
             old_retired=True, namespace_changed=True),
    ]


def test_native_runtime_dependencies_are_not_user_reload_candidates(tmp_path):
    from dsh.cordis.hmr_changes import excluded
    from dsh.cordis import hmr_partial
    import urllib.parse
    assert excluded(Path(hmr_partial.__file__).resolve().as_uri())
    assert excluded(Path(urllib.parse.__file__).resolve().as_uri())
    assert excluded((Path(sysconfig.get_path('purelib'))/'dependency.py').resolve().as_uri())
    assert not excluded((tmp_path/'plugin.py').resolve().as_uri())
