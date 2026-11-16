"""Exercise the ordinary-event exporter through a fixed-record channel harness."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts import rc022_otel_http_probe as collectors


def cases():
    rows=[dict(entry,event=True,retryAfter='20' if entry['mode']=='retry-deadline' else '0.001') for entry in collectors.cases() if entry['mode']!='config']
    rows += [dict(mode=mode,abort=abort,options={},env={},event=True,retryAfter='20')
        for mode,abort in [('ok','before'),('timeout','delay'),('retry-once','delay')]]
    rows += [dict(mode=mode,options={},env={},event=True,responseEncoding=coding)
        for mode in ('ok','oversized') for coding in ('gzip','deflate','br','zstd')]
    return rows


def prepare(output):
    collectors.prepare(output)
    (output/'inputs.json').write_text(json.dumps(cases()),encoding='utf-8')
    return [output/'inputs.json']


async def observe():
    import re
    from dsh.session.otel_event_http_current import EventHttpExporter
    rows=await collectors.observe(cases(),EventHttpExporter)
    for row in rows:
        for warning in row['warnings']:
            if warning['error']:warning['error']=re.sub(r'https?://(?:127\.0\.0\.1|localhost):[0-9]+/logs','<collector>',warning['error'])
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_otel_http.mts','Actual ordinary-event HTTP exporter, injected into a fixed-record Session harness solely to compare HTTP behavior.',
        [Path(__file__).resolve(),ROOT/'scripts/rc022_otel_http_probe.py',ROOT/'dsh/session/otel_event_http_current.py',
         ROOT/'dsh/session/otel_http_current.py',ROOT/'dsh/host/http_decode.py'],prepare=prepare)
