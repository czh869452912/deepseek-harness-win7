from functools import lru_cache
import hashlib
from pathlib import Path
import re


WHITESPACE = r'[\u0009-\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]'
CASE_FOLDING_SHA256 = '34f97be27ca68fdd2d3fdbb4a648c545f473c8089eafc50df792afbd8ea5650f'


def trim_text(value):
    return re.sub('^' + WHITESPACE + '+|' + WHITESPACE + '+$', '', value)


def verify_case_folding(path=None):
    path = Path(path) if path is not None else Path(__file__).parent / 'bin/unicode/CaseFolding.txt'
    if hashlib.sha256(path.read_bytes()).hexdigest() != CASE_FOLDING_SHA256:
        raise RuntimeError('Pinned Unicode case-folding data differs')
    return path


@lru_cache(maxsize=1)
def _fold_classes():
    path = verify_case_folding()
    classes = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        parts = line.split('#')[0].strip().split(';')
        if len(parts) < 3 or parts[1].strip() not in ('C', 'S'):
            continue
        original, mapped = int(parts[0], 16), int(parts[2].strip(), 16)
        classes.setdefault(mapped, set()).update([original, mapped])
    return {chr(member): tuple(sorted(members)) for members in classes.values() for member in members}


def literal_pattern(text):
    equivalents = _fold_classes()
    text = text.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='surrogatepass')
    def character_pattern(character):
        values = equivalents.get(character, (ord(character),))
        alternatives = []
        for codepoint in values:
            if codepoint > 0xffff:
                surrogate = codepoint - 0x10000
                alternatives.extend([re.escape(chr(codepoint)), re.escape(chr(0xd800 + (surrogate >> 10)) + chr(0xdc00 + (surrogate & 0x3ff)))])
            elif 0xd800 <= codepoint <= 0xdbff:
                alternatives.append(re.escape(chr(codepoint)) + r'(?![\udc00-\udfff])')
            elif 0xdc00 <= codepoint <= 0xdfff:
                alternatives.append(r'(?<![\ud800-\udbff])' + re.escape(chr(codepoint)))
            else:
                alternatives.append(re.escape(chr(codepoint)))
        return alternatives[0] if len(alternatives) == 1 else '(?:' + '|'.join(alternatives) + ')'
    return (WHITESPACE + '+').join(''.join(character_pattern(character) for character in part)
                                 for part in re.split(WHITESPACE + '+', text))
