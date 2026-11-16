"""Pair original manager private schema/validation/conversion without a fleet."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    patches=[{},dict(enabled=False),dict(startupTimeoutMs=1),dict(startupTimeoutMs=0),dict(closeTimeoutMs=0),
        dict(command=''),dict(url=''),dict(command='cross',url='http://local'),dict(args=['cross']),dict(env={'A':'x'}),dict(cwd='cross'),dict(headers={'X':'x'}),
        dict(reconnect=dict(initialDelayMs=10,maxDelayMs=2)),dict(reconnect=dict(maxAttempts=0)),
        dict(command='${x${credential:KEY}'),dict(command='${credential:KEY}'),dict(url='http://${credential:KEY}'),dict(headers={'X':'${env:BAD}'}),dict(args=['${credential:KEY','${credential:KEY}']),dict(extra='preserved')]
    for transport in ('stdio','streamable-http'):
        base=dict(transport=transport,**(dict(command='controlled') if transport=='stdio' else dict(url='http://local')))
        for patch in patches:rows.append(dict(name='managed',entry=dict(base,**patch)))
        for name in ('','a.b','__proto__','0','x'*32,'x'*33,'bad\n','\u6587'):
            rows.append(dict(name=name,entry=base))
    return rows


async def observe():
    from dsh.mcp.manager_entries_current import SERVER_ENTRY_SCHEMA,validate_entries,to_client_config
    rows=[]
    for case in cases():
        try:
            entry=SERVER_ENTRY_SCHEMA(case['entry']);validate_entries({case['name']:entry})
            client=to_client_config(case['name'],entry)
            # Conversion clones the transport collections.
            for key in ('args','env','headers'):
                if key in client:assert client[key] is not entry[key]
            result=dict(entry=entry,client=client)
        except Exception as error:result=dict(error=dict(name=getattr(error,'name','Error'),message=str(error)))
        rows.append(dict(input=case,result=result))
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_manager_entries.mts','Original manager entry schema and exact write-time validation order, transport-field rejection, template grammar, reconnect cross-field bounds and client config conversion with transport collection copies. Fleet lifecycle and Remote integration remain separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/manager_entries_current.py'],prepare=prepare)
