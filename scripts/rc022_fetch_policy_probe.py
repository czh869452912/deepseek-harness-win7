"""Network-free fetch policy and pinned charset vocabulary/byte projections."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    urls = ['', 'not a url', '//host/path', 'http://', 'https://[', 'ftp://host/path', 'file:///tmp', 'file://[',
            'data:text/plain,x', 'mailto:x@y', 'https://user:pass@host', 'https://@host/path',
            'http://127.1/path', 'HTTP://EXAMPLE.COM:80/a/../b?q=\'x#f', 'https://例子.测试/路径',
            'http://[::1]:8080/a', 'http://localhost/page', 'https://host/a\\b', ' https://host/\tpath\n',
            'https://host/a/%2e%2e/b', 'file://user@host/path', 'file://host:3/path']
    urls += ['https://host/'+suffix for suffix in ('a'*2035, 'a'*2036, '🙂'*1024, 'a'*2034+'🙂')]
    rows = [dict(kind='url', value=value) for value in urls]
    types = [None, '', 'text/html', 'application/xhtml+xml', 'text/plain', 'text/not-known', 'application/json',
             'application/xml', 'application/a+json', 'image/svg+xml', 'image/png', 'application/pdf', 'TEXT/HTML',
             ' text/plain \ufeff', 'text/plain\x85', 'text/plain; charset=UTF-8', 'text/plain; charset="iso-8859-1"',
             'text/plain; charset=', 'text/plain; charset=""', 'text/plain; x=y; CHARSET = "GB2312" ;next=x',
             'text/plain; charset=utf-8, gbk', 'text/plain; charset=\x85utf-8', 'text/plain\n; charset=utf8']
    rows += [dict(kind='content', value=value) for value in types]
    resource = json.loads((ROOT/'dsh/resources/text_decoder_022.json').read_text(encoding='utf-8'))
    labels = list(resource['aliases'])+[None, '', 'not-a-charset', 'UTF-8', ' utf8\n', '\ufeffutf8', 'utf-8,gbk',
                                      'gbk,utf8', 'utf-8 utf8', 'gb2312,gbk', ',', '\x85utf8']
    rows += [dict(kind='label', value=value) for value in labels]
    rows += [dict(kind='decode', charset=charset, data=list(range(256)), stream=False) for charset in resource['singleByte']]
    for charset in ('utf-8', 'utf-16le', 'utf-16be', 'big5', 'euc-jp', 'iso-2022-jp', 'shift_jis', 'euc-kr', 'gbk', 'gb18030', 'utf-8,gbk'):
        samples = [b'', b'ASCII', b'\xef\xbb\xbftext', b'\xff\xfea\0', b'\xfe\xff\0a', b'\x80', b'\xa0', b'\xff', bytes(range(256)), b'\xe4\xb8\xad', b'\xe4\xb8']
        rows += [dict(kind='decode', charset=charset, data=list(data), stream=stream) for data in samples for stream in (False, True)]
        generator = random.Random(0)
        rows += [dict(kind='decode', charset=charset, data=[generator.randrange(256) for _ in range(size)], stream=stream)
                 for size in (1, 2, 3, 4, 8, 16, 32, 65) for _ in range(8) for stream in (False, True)]
        rows += [dict(kind='chunks', charset=charset, data=list(data)) for data in samples]
    for pointer in (0, 1, 35, 36, 37, 7457, 7458, 189000, 1237575, 1587599):
        rest = pointer; fourth = rest % 10+0x30; rest //= 10; third = rest % 126+0x81; rest //= 126
        second = rest % 10+0x30; first = rest//10+0x81
        rows.append(dict(kind='chunks', charset='gb18030', data=[first, second, third, fourth]))
    escapes = [b'\x1b', b'\x1b(', b'\x1b$', b'\x1b(X', b'\x1b$X', b'\x1b(B', b'\x1b(J', b'\x1b(I', b'\x1b$B', b'\x1b$@']
    for prefix in [b'']+escapes[5:]:
        samples = escapes+[bytes(range(256)), b'\x21\n\x24\x22', b'\x21\x1b(B', b'\x21\x0e\x24\x22']
        generator = random.Random(22)
        samples += [bytes(generator.randrange(256) for _ in range(32)) for _ in range(32)]
        for sample in samples:
            rows.append(dict(kind='chunks', charset='iso-2022-jp', data=list(prefix+sample)))
            rows.append(dict(kind='decode', charset='iso-2022-jp', data=list(prefix+sample), stream=False))
    return rows


def prepare(output):
    path = output/'inputs.json'; path.write_text(json.dumps(cases()), encoding='utf-8'); return [path]


async def observe():
    from dsh.web import fetch_policy_current as policy
    rows = []
    for entry in cases():
        try:
            kind = entry['kind']
            if kind == 'url':
                url = policy.validateFetchUrl(entry['value'])
                result = {key: url[key] for key in ('href', 'origin', 'protocol', 'pathname', 'search', 'hash')}
            elif kind == 'content': result = dict(kind=policy.classifyContentType(entry['value']), charset=policy.parseCharset(entry['value']))
            else:
                decoder = policy.decoderForCharset(entry.get('charset', entry.get('value')))
                result = dict(encoding=decoder.encoding, fatal=decoder.fatal)
                if kind == 'chunks':
                    try:
                        outputs = []; result['chunks'] = outputs
                        for byte in entry['data']: outputs.append(decoder.decode(bytes([byte]), stream=True))
                        outputs.append(decoder.decode(b''))
                        result.update(chunks=outputs)
                    except UnicodeError: result.update(decodeFailed=True)
                elif kind == 'decode':
                    try: result.update(decoded=decoder.decode(bytes(entry['data']), stream=entry['stream']))
                    except UnicodeError: result.update(decodeFailed=True)
        except Exception as error: result = dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))
        rows.append(dict(kind=entry['kind'], result=result))
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_fetch_policy.mts', 'Pure fetch URL/MIME/charset policy, accepted labels and byte decoding projections.',
               [Path(__file__).resolve(), ROOT/'dsh/web/fetch_policy_current.py', ROOT/'dsh/resources/text_decoder_022.json'], prepare=prepare)
