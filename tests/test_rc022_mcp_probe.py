import asyncio
import pytest

from dsh.mcp.probe_current import negotiate_era
from scripts.rc022_mcp_probe_probe import observe, cases


def test_probe_window_and_negotiation_corpus():
    rows=asyncio.run(observe())
    assert len(rows)==len(cases())==161
    assert all(row['restored']==dict(message=True,error=True) and row['closeRestored'] for row in rows)
    assert any(len(row['requests'])==2 for row in rows)


def test_probe_cancellation_restores_callbacks_and_channel_owns_late_send():
    async def run():
        entered=asyncio.Event();release=asyncio.Event();messages=[]
        class Channel:
            onerror=None
            onclose=None
            async def start(self):pass
            async def send(self,packet):
                entered.set();await release.wait()
                self.onmessage(dict(jsonrpc='2.0',id=packet['id'],result={}))
        channel=Channel();channel.onmessage=messages.append;saved=channel.onmessage
        task=asyncio.create_task(negotiate_era(dict(kind='auto',modernVersions=['2026-07-28'],fallbackAvailable=True),channel))
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert channel.onmessage is saved
        assert len(channel._probe_send_tasks)==1
        release.set();await asyncio.gather(*list(channel._probe_send_tasks));await asyncio.sleep(0)
        assert not channel._probe_send_tasks
        assert len(messages)==1
    asyncio.run(run())
