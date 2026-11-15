"""Pair listener, trusted authority and browser-origin admission facts."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[]
    hosts=['localhost','127.8.9.10:80','0x7f000001','127.1','[::1]','[0:0:0:0:0:0:0:1]:443','10.1.2.3:3080','[fd00::1]:9999','[::ffff:10.1.2.3]:3080','[fe80::1]:3080','remote.example:443','REMOTE.EXAMPLE:80','remote.example:9000','evil.example','xn--fsqu00a.xn--0zwm56d','例子.测试']
    for host in hosts:
        for protocol in ('http:','https:'):
            for origin in (None,protocol+'//'+host,'https://remote.example:443','ftp://'+host,'null'):
                headers=dict(host=host)
                if origin is not None:headers['origin']=origin
                rows.append(dict(request=dict(headers=headers),trusted=['remote.example:443','xn--fsqu00a.xn--0zwm56d'],bind='10.1.2.3',protocol=protocol))
    for bind,host in [('fd00::1','[fd00:0:0:0:0:0:0:1]:3080'),('::ffff:10.1.2.3','[::ffff:a01:203]:3080'),('fe80::1%lo','[fe80::1]:3080')]:
        rows.append(dict(request=dict(headers=dict(host=host)),trusted=[],bind=bind,protocol='http:'))
    for headers in ({},{'host':['localhost']},{'host':'localhost','sec-fetch-site':'cross-site'},{'host':'remote.example:80'},{'host':'remote.example:443'}):
        rows.append(dict(request=dict(headers=headers),trusted=['remote.example'],bind=None,protocol='https:'))
    return rows


async def observe():
    from dsh.host.connection.trust_current import is_trusted_api_request,is_remote_authority
    return [dict(index=index,allowed=is_trusted_api_request(row['request'],row['trusted'],row['bind'],row['protocol'])) for index,row in enumerate(cases())]+[dict(authority=value,remote=is_remote_authority(value)) for value in ('localhost','127.1','[::1]','remote.example','10.1.2.3','invalid:port')]


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_connection_trust.mts','Actual protocol-aware upstream trust fence, bind address and zone matching, numeric/IPv6/IDN normalization, Origin HTTP(S) scheme ports, remote authority classification.',[Path(__file__).resolve(),ROOT/'dsh/host/connection/trust_current.py',ROOT/'dsh/host/http_proxy_policy.py'],prepare=prepare)
