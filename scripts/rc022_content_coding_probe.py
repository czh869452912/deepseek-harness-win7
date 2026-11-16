"""Fixed Node byte corpus through real Source and Native fetch transports."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe, rc022_http_fetch_probe as http


def cases():
    return json.loads((ROOT/'scripts/oracles/rc022_content_coding_cases.json').read_text(encoding='utf-8'))['rows']


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return[path]


async def observe():
    return await http.observe(cases())

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_http_fetch.mts','Pinned Node compressed byte corpus over real HTTP: bounded decoding, chain policy and recovery.',
        [Path(__file__).resolve(),ROOT/'dsh/host/http_decode.py',ROOT/'dsh/host/http_request.py',
         ROOT/'scripts/oracles/rc022_content_coding_cases.json'],prepare=prepare)
