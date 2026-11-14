import asyncio

import pytest

from scripts.rc022_hmr_ready_probe import observe


@pytest.mark.asyncio
async def test_profile_startup_barrier_shutdown_and_disk_baseline(tmp_path):
    assert await asyncio.wait_for(observe(tmp_path/'observations'), 10) == [
        dict(case='requires-ready', rejected=True),
        dict(case='commit', mutation=42, before=[], after=['refresh']),
        dict(case='cancel', mutation=42, before=[], after=[]),
        dict(case='baseline-error', mutation=42, before=[], after=['refresh']),
        dict(case='initial-profile-and-linked-records', stale=['sibling.py']),
    ]
