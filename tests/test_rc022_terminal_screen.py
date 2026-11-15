import hashlib
import json
from pathlib import Path

import pytest

from dsh.api.terminal_screen_authorized import page_lines,render_lines,last_content_row,cursor_line_start
from dsh.terminal.grapheme import segments,tail_within,utf8

ROOT=Path(__file__).resolve().parents[1]


def test_unicode16_official_conformance_and_generated_identities():
    manifest=json.loads((ROOT/'dsh/terminal/unicode16/manifest.json').read_text(encoding='utf-8'))
    for name,record in manifest['outputs'].items():
        data=(ROOT/name).read_bytes()
        assert len(data)==record['bytes'] and hashlib.sha256(data).hexdigest()==record['sha256']
    cases=json.loads((ROOT/'tests/fixtures/unicode/grapheme16.json').read_text(encoding='utf-8'))
    assert len(cases)==manifest['conformance_cases']==1093
    for expected in cases:assert segments(''.join(expected))==expected


@pytest.mark.parametrize('text',['👨\u200d👩\u200d👧\u200d👦','👩🏽\u200d💻','🇨🇳','a\u0301','क्ष'])
def test_page_never_splits_the_newest_grapheme(text):
    assert segments(text)==[text]
    for limit in range(len(utf8(text))):
        assert tail_within('old'+text,limit)==''
        assert page_lines(['old'+text],dict(offset=0,count=1,maxBytes=limit))==dict(text='',totalLines=1,lineBegin=0,lineEnd=1,truncated=True)
    assert tail_within('old'+text,len(utf8(text)))==text


def test_pages_keep_newest_whole_lines_and_empty_line_metadata():
    assert page_lines(['first','second','third','fourth'],dict(offset=0,count=4,maxBytes=12))==dict(text='third\nfourth',totalLines=4,lineBegin=0,lineEnd=2,truncated=True)
    assert page_lines(['a'],dict(offset=9,count=5,maxBytes=0))==dict(text='',totalLines=1,lineBegin=9,lineEnd=9,truncated=False)
    assert page_lines([''],dict(offset=0,count=1,maxBytes=0))==dict(text='',totalLines=1,lineBegin=0,lineEnd=1,truncated=False)
    assert segments('\ud83d\ude00')==['😀'] and utf8('\ud800')==b'\xef\xbf\xbd'


def test_dense_buffer_wrap_cursor_and_exact_javascript_trim_end():
    buffer=dict(baseY=0,cursorY=1,lines=[dict(text='first ',trimmed='first',isWrapped=False),
        dict(text='wrapped\ufeff',trimmed='wrapped\ufeff',isWrapped=True),dict(text='keep\x1c',trimmed='keep\x1c',isWrapped=False)])
    assert last_content_row(buffer)==2 and cursor_line_start(buffer)==0
    assert render_lines(buffer,0,3)==['first wrapped','keep\x1c']
    assert render_lines(buffer,1,2)==['wrapped']
