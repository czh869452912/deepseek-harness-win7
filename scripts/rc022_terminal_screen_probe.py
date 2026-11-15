"""Screen projection and grapheme-safe byte paging against pinned Source helpers."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    conformance=json.loads((ROOT/'tests/fixtures/unicode/grapheme16.json').read_text(encoding='utf-8'))
    strings=[''.join(case) for case in conformance]+['a👨\u200d👩\u200d👧\u200d👦b','👩🏽\u200d💻🇨🇳🇨🇦a\u0301','क्ष','\ud800x\udc00','\ud83d\ude00']
    page_sets=[[],[''],['first','second','third','fourth'],['前缀终端'],['🇨🇳👨\u200d👩\u200d👧\u200d👦a\u0301'],['क्ष','👩🏽\u200d💻'],['one','','last'],['\ud800','\ud83d\ude00']]
    pages=[dict(lines=lines,request=dict(offset=offset,count=count,maxBytes=maximum))
           for lines in page_sets for offset in (0,1,2,9) for count in (0,1,5) for maximum in (0,1,3,7,12,1000)]
    buffers=[]
    for lines,base,cursor in [([],0,0),([('one ',False),('two ',False),('',False)],0,0),
            ([('0123456789',False),('abcdefghi ',True),('jk  ',True),('',False)],0,2),
            ([('history ',False),('终端  ',False),('wide😀 ',True),('   ',False),('',False)],1,2),
            ([('tail\ufeff',False),('keep\x1c',False),('x\u00a0',False)],0,2)]:
        buffers.append(dict(baseY=base,cursorY=cursor,lines=[dict(text=text,isWrapped=wrapped,trimmed=text.rstrip(' ')) for text,wrapped in lines]))
    return dict(strings=strings,pages=pages,buffers=buffers)


async def observe():
    from dsh.terminal.grapheme import segments
    from dsh.api.terminal_screen_authorized import page_lines,render_lines,last_content_row,cursor_line_start
    inputs=cases();rows=[dict(name='grapheme',index=index,value=segments(text)) for index,text in enumerate(inputs['strings'])]
    rows += [dict(name='page',index=index,value=page_lines(case['lines'],case['request'])) for index,case in enumerate(inputs['pages'])]
    for index,buffer in enumerate(inputs['buffers']):
        rows.append(dict(name='buffer',index=index,last=last_content_row(buffer),cursor=cursor_line_start(buffer),
            ranges=[render_lines(buffer,start,end) for start,end in [(-1,100),(1,3),(2,2)]]))
    # Match the Source JSON carrier's representation of explicit UTF-16 pairs.
    return json.loads(json.dumps(rows,ensure_ascii=True))


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_terminal_screen.mts','Screen helper comparison: all Unicode 16 conformance sequences plus compound emoji/Indic/surrogate cases against actual Node Intl.Segmenter; exact newest-relative pages across empty, byte, offset and count boundaries; dense buffer snapshots cover cursor, trailing rows, wrapped rows and JS trimEnd. Buffers are controlled snapshots; no emulator, PTY or BrowserTerminal acceptance.',
        [Path(__file__).resolve()]+[ROOT/path for path in ('dsh/terminal/grapheme.py','dsh/terminal/unicode16/grapheme.json','dsh/terminal/unicode16/manifest.json','tests/fixtures/unicode/grapheme16.json','dsh/api/terminal_screen_authorized.py')],prepare=prepare)
