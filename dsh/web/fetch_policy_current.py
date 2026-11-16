"""Pure URL/content policy and Node TextDecoder-compatible charset selection."""
import codecs
import bisect
import json
import re
from pathlib import Path

from dsh.host.http_proxy_policy import JS_SPACE
from dsh.host.url_current import _url
from dsh.web.web_service import WebError

WEB_FETCH_MAX_URL_LENGTH = 2048
with (Path(__file__).resolve().parents[1]/'resources/text_decoder_022.json').open(encoding='utf-8') as _stream:
    _DECODERS = json.load(_stream)
_CODECS = {'utf-16le': 'utf-16-le', 'utf-16be': 'utf-16-be'}


def _decodeUtf8(data, stream, fatal):
    result = []; index = 0
    def invalid():
        if fatal: raise UnicodeDecodeError('utf-8', data, index, index+1, 'invalid UTF-8 sequence')
        result.append('\ufffd')
    while index < len(data):
        first = data[index]
        if first < 128: result.append(chr(first)); index += 1; continue
        size = 2 if 0xc2 <= first <= 0xdf else 3 if 0xe0 <= first <= 0xef else 4 if 0xf0 <= first <= 0xf4 else 0
        if not size: invalid(); index += 1; continue
        count = 1
        while count < size and index+count < len(data):
            byte = data[index+count]
            low = 0xa0 if count == 1 and first == 0xe0 else 0x90 if count == 1 and first == 0xf0 else 0x80
            high = 0x9f if count == 1 and first == 0xed else 0x8f if count == 1 and first == 0xf4 else 0xbf
            if not low <= byte <= high: break
            count += 1
        if count == size: result.append(data[index:index+size].decode('utf-8')); index += size
        elif index+count == len(data) and stream: break
        else: invalid(); index += count
    return ''.join(result), index


def _decodeIso(data, state, flag, stream):
    result = []; index = 0; table = _DECODERS['iso2022']
    while index < len(data):
        byte = data[index]
        if byte == 27:
            available = data[index:index+3]
            if len(available) < 3 and (len(available) == 1 or available[1] in (36, 40)):
                if not stream: result.append('\ufffd'); index = len(data)
                break
            target = {b'\x1b(B': 'ascii', b'\x1b(J': 'roman', b'\x1b(I': 'katakana',
                      b'\x1b$B': 'jis', b'\x1b$@': 'jis'}.get(available)
            if target is None: result.append('\ufffd'); index += 1; flag = False; continue
            if flag: result.append('\ufffd')
            state = target; flag = True; index += 3; continue
        flag = False
        if state == 'jis':
            leaf = table['single'][byte]
            if leaf is None:
                if index+1 == len(data):
                    if not stream: result.append('\ufffd'); index += 1
                    break
                leaf = table['pairs'][str(byte)][data[index+1]]
            result.append(leaf[0]); index += leaf[1]
            if byte in (10, 13): state = 'ascii'
            continue
        if byte in (10, 13) and state == 'katakana': state = 'ascii'
        if state == 'katakana': value = chr(0xff61+byte-0x21) if 0x21 <= byte <= 0x5f else chr(byte) if byte in (10, 13) else '\ufffd'
        elif byte >= 128 or byte in (14, 15): value = '\ufffd'
        elif state == 'roman' and byte in (92, 126): value = '\u00a5' if byte == 92 else '\u203e'
        else: value = chr(byte)
        result.append(value); index += 1
    return ''.join(result), index, state, flag


def _decodeDbcs(data, encoding, stream):
    table = _DECODERS['dbcs'][encoding]; result = []; index = 0
    while index < len(data):
        first = data[index]; leaf = table['single'][first]
        if leaf is None:
            if index+1 == len(data):
                if not stream: result.append('\ufffd')
                break
            second = data[index+1]; leaf = table['pairs'][str(first)][second]
            if leaf is None:
                if encoding == 'gb18030':
                    if index+2 == len(data):
                        if not stream: result.append('\ufffd')
                        break
                    third = data[index+2]
                    if 0x81 <= third <= 0xfe:
                        if index+3 == len(data):
                            if not stream: result.append('\ufffd')
                            break
                        fourth = data[index+3]
                        if 0x30 <= fourth <= 0x39:
                            pointer = (((first-0x81)*10+second-0x30)*126+third-0x81)*10+fourth-0x30
                            if str(pointer) in table['special']: output = table['special'][str(pointer)]
                            else:
                                ranges = table['ranges']
                                position = bisect.bisect_right(_GB_STARTS, pointer)-1
                                start, end, code, step = ranges[position]
                                assert start <= pointer <= end
                                output = chr(code+(pointer-start)*step)
                            leaf = [output, 4]
                        else: leaf = ['\ufffd', 1]
                    else: leaf = ['\ufffd', 1]
                else:
                    if index+2 == len(data):
                        if not stream: result.append('\ufffd')
                        break
                    leaf = table['triples'][str((first << 8)|second)][data[index+2]]
        result.append(leaf[0]); index += leaf[1]
    return ''.join(result), index


def parseFetchUrl(value):
    try: url = _url(value)
    except (ValueError, TypeError) as error:
        raise WebError('invalid URL: '+value, 'WEB_INVALID_URL', cause=error)
    if url['protocol'] not in ('http:', 'https:'):
        raise WebError('unsupported URL scheme "'+url['protocol']+'" (only http and https are allowed)', 'WEB_INVALID_URL')
    if url['credentials']: raise WebError('credentials in URLs are not allowed', 'WEB_BLOCKED_URL')
    return url


def validateFetchUrl(value):
    if len(value.encode('utf-16-le', 'surrogatepass'))//2 > WEB_FETCH_MAX_URL_LENGTH:
        raise WebError('URL exceeds the maximum length of 2048', 'WEB_INVALID_URL')
    return parseFetchUrl(value)


def isSameOrigin(a, b):
    return a['origin'] == b['origin']


def classifyContentType(value):
    mime = (value or '').split(';', 1)[0].strip(JS_SPACE).lower()
    if mime in ('text/html', 'application/xhtml+xml'): return 'html'
    if mime.startswith('text/') or mime in ('application/json', 'application/xml') or mime.endswith(('+json', '+xml')): return 'text'
    return None


def parseCharset(value):
    space = '['+re.escape(JS_SPACE)+']*'
    match = re.search(';'+space+'charset'+space+'='+space+'"?([^";]+)"?', value or '', re.I | re.ASCII)
    return match.group(1).strip(JS_SPACE).lower() if match else None


class TextDecoder:
    def __init__(self, encoding, fatal=False):
        self.encoding, self.fatal = encoding, fatal
        self._pending = b''; self._bomSeen = False; self._codec = None
        self._isoState = 'ascii'; self._isoFlag = False

    def decode(self, data, stream=False):
        table = _DECODERS['singleByte'].get(self.encoding)
        if table is not None: return ''.join(table[value] for value in data)
        if self.encoding in ('utf-8', 'iso-2022-jp'):
            input_size = len(data)
            data = self._pending+data
            try:
                if self.encoding == 'utf-8': value, consumed = _decodeUtf8(data, stream, self.fatal)
                else:
                    value, consumed, self._isoState, self._isoFlag = _decodeIso(data, self._isoState, self._isoFlag, stream)
                    # Pinned Node/ICU allocates two UTF-16 units per input byte.
                    # Replaying an invalid escape buffered across calls can overflow it.
                    if input_size and len(value) > input_size*2:
                        raise UnicodeDecodeError('iso-2022-jp', data, 0, 1, 'decoder output overflow')
            except UnicodeError:
                self._pending = b''; self._bomSeen = False
                self._isoState = 'ascii'; self._isoFlag = False
                raise
            self._pending = data[consumed:] if stream else b''
            if not self._bomSeen and value:
                if self.encoding == 'utf-8' and value.startswith('\ufeff'): value = value[1:]
                self._bomSeen = True
            if not stream:
                self._bomSeen = False; self._isoState = 'ascii'; self._isoFlag = False
            return value
        if self.encoding in _DECODERS.get('dbcs', {}):
            data = self._pending+data
            value, consumed = _decodeDbcs(data, self.encoding, stream)
            self._pending = data[consumed:] if stream else b''
            return value
        if self._codec is None:
            self._codec = codecs.getincrementaldecoder(_CODECS[self.encoding])('strict' if self.fatal else 'replace')
        try: value = self._codec.decode(data, final=not stream)
        except UnicodeError:
            self._codec = None; self._bomSeen = False
            raise
        if not self._bomSeen and value:
            if self.encoding in ('utf-8', 'utf-16le', 'utf-16be') and value.startswith('\ufeff'): value = value[1:]
            self._bomSeen = True
        if not stream: self._codec = None; self._bomSeen = False
        return value


def _encoding(label):
    # Encoding labels use the ASCII whitespace set, independently of trim().
    return _DECODERS['aliases'].get(label.strip(' \t\n\f\r').lower())


def decoderForCharset(charset=None):
    declared = charset if charset is not None else 'utf-8'
    encoding = _encoding(declared)
    if encoding is not None: return TextDecoder(encoding)
    if any(_encoding(label) == 'utf-8' for label in re.split('['+re.escape(JS_SPACE)+',]+', declared)):
        return TextDecoder('utf-8', fatal=True)
    raise WebError('unsupported charset "'+declared+'"', 'WEB_UNSUPPORTED_CONTENT_TYPE')


_GB_STARTS = [row[0] for row in _DECODERS.get('dbcs', {}).get('gb18030', {}).get('ranges', [])]
