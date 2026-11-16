"""Pair original public advertised-root parsing without starting a listener."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    return ['https://app.example','https://app.example/ui','HTTPS://APP.EXAMPLE:443/UI',
        'http://app.example:80/a','https://[::1]:8443/ui','https://[0:0::1]/',
        'https://app.example/a/../b','https://app.example/a/%2e%2e/b','https://app.example/a/./',
        'https://app.example/a/..','https://app.example//a//','https://app.example/a\\b',
        'https://\u4e2d\u6587.example/\u8def\u5f84','http://127.1','http://0x7f000001/',
        'https://app.example/a`<>"{}','https://app.example/a[]^|%zz',
        '/ui','ftp://host/','https:///ui','https://','https://\\foo',
        'https://user@example.com/','https://@example.com/','https://app.example/?',
        'https://app.example/#','https://app.example/ ','https://app.example/\x7f',
        'https://app.example/\n','https://[broken/','https://[foo]/','https://app.example:65536/',
        'https://app.example:abc/','https://a%00b/','http://999.1/','https://app.example/\ud800']


async def observe():
    from dsh.bundle.web_app.current import parse_public_url
    rows=[]
    for value in corpus():
        try:rows.append(dict(value=value,url=parse_public_url(value)))
        except ValueError as error:rows.append(dict(value=value,error=str(error)))
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_web_runtime.mts','Original public-root validation and WHATWG URL normalization: proxy prefixes, dot segments, Unicode/ASCII host and paths, numeric IPv4, IPv6, ports and rejection precedence.',[Path(__file__).resolve(),ROOT/'dsh/bundle/web_app/current.py'],prepare=prepare)
