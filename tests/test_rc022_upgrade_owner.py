import asyncio
import pytest

from scripts.rc022_upgrade_owner_probe import scenario


@pytest.mark.asyncio
@pytest.mark.parametrize('secure,peer_end',[(False,False),(True,False),(False,True)])
async def test_returned_upgrade_callback_keeps_transferred_plain_or_tls_socket(secure,peer_end):
    row=await asyncio.wait_for(scenario(secure,peer_end),5)
    assert row==dict(secure=secure,peerEnd=peer_end,status=101,calls=['handler-returned'],replies=['ACK:hello','ACK:world'],
        halfOpen=True if peer_end else None,closed=True,ownerJobsSettled=True,trackedSockets=0)
