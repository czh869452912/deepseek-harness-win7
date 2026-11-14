import asyncio

import pytest

from scripts.rc022_hmr_watch_probe import observe


@pytest.mark.asyncio
async def test_real_profile_watchers_recompose_and_replace_their_own_provider(tmp_path):
    rows = await asyncio.wait_for(observe(tmp_path/'observations'), 35)
    assert rows == [
        dict(step='ready', before='initial', value='edited-before-ready'),
        dict(step='home', value='home'),
        dict(step='home-unlink', value='edited-before-ready'),
        dict(step='dependencies-only', reloaded=False),
        dict(step='bundles', bundled=True, value='edited-before-ready'),
        dict(step='unchanged-inputs', reloaded=False),
        dict(step='provider-replacement', old_active=False, value='after-hmr-replacement'),
        dict(mode='cancel', before='initial', value=None, active=False),
    ]
