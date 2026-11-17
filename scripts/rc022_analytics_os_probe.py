"""Sample the actual host through the pinned Source and default Native sources."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.client.analytics_os_current import collectEnvironment
    from dsh.core.abort import AbortController
    return await collectEnvironment(dict(timeoutMillis=5000,maxOutputBytes=16384,signal=AbortController().signal))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_analytics_os.mts','Actual development host static environment, selected OS/CPU/memory fields and fixed bounded metadata commands. This is not Windows 7 qualification.',
        [Path(__file__).resolve(),ROOT/'dsh/client/analytics_os_current.py',ROOT/'dsh/client/analytics_environment_current.py',ROOT/'dsh/client/analytics_environment_query_current.py'])
