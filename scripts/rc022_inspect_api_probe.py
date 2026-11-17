"""Bounded exact digests for every current Service/Event contract and type closure."""
import hashlib
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def digest(value):
    from dsh.cordis.json_text import stringify_json
    def normalize(item):
        if isinstance(item,list):return [normalize(value) for value in item]
        if isinstance(item,dict):return {key:normalize(item[key]) for key in sorted(item,key=lambda key:key.encode('utf-16-be','surrogatepass'))}
        return item
    data=stringify_json(normalize(value)).encode('utf-8')
    return dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))


async def observe():
    from dsh.core.session.json import UNDEFINED
    from dsh.extensions.inspect_api_current import SERVICE_API,HOST_EVENTS,query_service_api,query_event_api
    from dsh.extensions.inspect_providers_current import host_inspect_providers
    rows=[]
    for kind,keys,query in [('service',[UNDEFINED,*[row['key'] for row in SERVICE_API],'','unknown','"中文\n'],query_service_api),
        ('event',[UNDEFINED,*[row['name'] for row in HOST_EVENTS],'','unknown','cordis/query','"中文\n'],lambda key:query_event_api(key,HOST_EVENTS))]:
        for key in keys:
            row=dict(kind=kind,key=None if key is UNDEFINED else key)
            try:row.update(digest(query(key)))
            except Exception as error:row['error']=str(error)
            rows.append(row)
    rows.append(dict(kind='manifests',value=[row['manifest'] for row in host_inspect_providers(None)]))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_inspect_api.mts',scope='All current generated Service and Host Event coding contracts, complete transitive referenced type closures, exact absence errors and four Host provider manifests. Responses are canonicalized and hashed to bound repeated generated declaration output; the complete raw generated catalog is retained as the pinned implementation resource.',
        extra_inputs=[Path(__file__).resolve(),ROOT/'dsh/extensions/inspect_api_current.py',ROOT/'dsh/extensions/inspect_providers_current.py',ROOT/'dsh/extensions/inspect_catalog_022.json'])
