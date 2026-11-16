"""Pair SDK 2 and Python disposable stdio negotiation over actual child processes."""
import asyncio
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.oracles.rc022_mcp_negotiation_peer import alive
from scripts.rc022_mcp_negotiation_probe import normalize
OUTPUT=None


async def observe():
    from dsh.mcp.stdio_current import CurrentStdioMcpTransport
    rows=[]
    for mode in ('legacy','modern','closed','timeout','hold'):
        log=OUTPUT/('native-'+mode+'.jsonl')
        client=CurrentStdioMcpTransport(sys.executable,[str(ROOT/'scripts/oracles/rc022_mcp_negotiation_peer.py'),str(log),mode],negotiation=dict(kind='auto',modernVersions=['2026-07-28'],fallbackAvailable=True,probe=dict(timeoutMs=1000 if mode=='timeout' else 2000)))
        connecting=asyncio.create_task(client.connect())
        try:
            if mode=='hold':
                async def seen():
                    while not log.exists() or 'server/discover' not in log.read_text(encoding='utf-8'):await asyncio.sleep(.005)
                await asyncio.wait_for(seen(),5)
                await client.close()
            await connecting
            value=dict(serverInfo=client.server_info,capabilities=client.server_capabilities,instructions=client.server_instructions,tools=await client.list_tools())
        except Exception as error:value=dict(error=normalize(error))
        finally:await client.close()
        events=[json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()];starts=[row for row in events if row['event']=='start']
        rows.append(dict(mode=mode,value=value,starts=len(starts),previousAlive=[row['previousAlive'] for row in starts],allClosed=all(not alive(row['pid']) for row in starts),requests=[row['packet'] for row in events if row['event']=='packet']))
    return rows


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(dict(output=str(output),python=sys.executable,peer=str(ROOT/'scripts/oracles/rc022_mcp_negotiation_peer.py'))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_stdio_negotiation.mts','Actual SDK base stdio transport and Python disposable sibling, exact packet logs, no overlapping processes, modern discovery without initialize, legacy fallback, mid-probe close/timeout and caller close. Loader integration has separate native tests; full SDK caches and supervisor lifecycle remain separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/stdio_current.py',ROOT/'dsh/mcp/result_current.py',ROOT/'dsh/mcp/schemas.py',ROOT/'dsh/mcp/resource_schemas_current.json',ROOT/'dsh/mcp/current.py',ROOT/'dsh/mcp/connection.py',ROOT/'scripts/oracles/rc022_mcp_negotiation_peer.py'],prepare=prepare)
