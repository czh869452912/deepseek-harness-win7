"""Pair actual SDK/Python in-place HTTP probes and business headers."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_mcp_negotiation_probe import normalize
MODES=['legacy','legacy-sse','modern','modern-sse','corrective','401','403','404','503','content','malformed','timeout','hold']
HEADERS={'Authorization':'controlled-local','Accept':'application/fixture','Mcp-Protocol-Version':'caller-stale','Mcp-Session-Id':'caller-session'}
PEER=None;URL=None;LOG=None


async def observe():
    from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
    rows=[]
    for mode in MODES:
        client=CurrentStreamableHttpMcpTransport(URL+'/native/'+mode,HEADERS,negotiation=dict(kind='auto',modernVersions=['2026-07-28'],fallbackAvailable=True,probe=dict(timeoutMs=50 if mode=='timeout' else 2000)))
        connecting=asyncio.create_task(client.connect())
        try:
            if mode=='hold':
                async def seen():
                    while not LOG.exists() or not any(row['path']=='/native/hold' and (row.get('packet') or {}).get('method')=='server/discover' for row in records()):await asyncio.sleep(.005)
                await asyncio.wait_for(seen(),5);await client.close()
            await connecting
            value=dict(serverInfo=client.server_info,capabilities=client.server_capabilities,instructions=client.server_instructions,tools=await client.list_tools(),resource=await client.request(dict(method='resources/read',params=dict(uri='doc://\u6587\u6863/one'))),sessionId=client.session_id)
        except Exception as error:value=dict(error=normalize(error))
        finally:await client.close()
        requests=[]
        for row in records():
            if row['path']=='/native/'+mode and row['httpMethod']=='POST':
                headers={key.lower():value for key,value in row['headers'].items() if key.lower() in ('content-type','accept','authorization') or key.lower().startswith('mcp-')}
                requests.append(dict(packet=row['packet'],headers=headers))
        assert not client._pending and not client._writers and not client._tasks
        assert not getattr(client._probe_channel,'_probe_send_tasks',())
        rows.append(dict(mode=mode,value=value,requests=requests))
    return rows


def records():return [json.loads(line) for line in LOG.read_text(encoding='utf-8').splitlines()]


def prepare(output):
    global PEER,URL,LOG
    LOG=output/'http-peer.jsonl'
    PEER=subprocess.Popen([sys.executable,str(ROOT/'scripts/oracles/rc022_mcp_http_negotiation_peer.py'),str(LOG)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    URL=PEER.stdout.readline().decode('utf-8').strip()
    assert URL.startswith('http://127.0.0.1:')
    path=output/'input.json';path.write_text(json.dumps(dict(url=URL,log=str(LOG),headers=HEADERS,modes=MODES)),encoding='utf-8');return [path]


def stop_peer():
    if PEER is None:return
    PEER.stdin.close();PEER.wait(timeout=10)
    assert PEER.returncode==0 and not PEER.stderr.read()
    PEER.stdout.close();PEER.stderr.close()


if __name__=='__main__':
    probe.native=observe
    try:probe.main('rc022_mcp_http_negotiation.mts','Actual SDK and Python in-place HTTP probes, JSON/SSE, corrective 400 RPC reply, authentication/5xx/content/timeout/close errors, modern body-derived business headers and handshake-only session assignment. Full raw request logs retained; observation compares POST packets and business headers, excluding socket/HTTP client defaults and asynchronous GET ordering.',[Path(__file__).resolve(),ROOT/'dsh/mcp/http_current.py',ROOT/'dsh/mcp/negotiated_protocol_current.py',ROOT/'scripts/oracles/rc022_mcp_http_negotiation_peer.py'],prepare=prepare)
    finally:stop_peer()
