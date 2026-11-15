"""Pure batch patch grammar and matching observations over a shared corpus."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def corpus():
    def patch(*lines):return '\n'.join(['*** Begin Patch']+list(lines)+['*** End Patch'])
    patches=[patch(),patch('*** Add File: a','+hello','+','*** Delete File: b'),patch('*** Update File: a','*** Move to: b','@@ context','-old','+new',' same','@@',' last','+tail','*** End of File','*** Add File: a'),patch('*** Update File: a','-old','+new'),patch('*** Update File: a','','-old','+new'),patch('*** Update File: a','@@','-old','+new','*** End of File','','@@','-last','+tail'),patch('*** Add File: a'),patch('*** Delete File: a'),patch('*** Update File: a','@@ anchor','+append'),patch('*** Update File: a','*** End of File','+append')]
    patches += ['\n \u0085\n'+patch('*** Add File: \u6d4b\U0001f9ea','+body')+'\u3000',"<<'EOF'\n"+patch('*** Add File: a','+body')+'\nEOF', '<<EOF\n'+patch()+'\nPREFIXEOF',patch('*** Add File: a','+body').replace('\n','\r\n'),patch('*** Add File: a','+body').replace('\n','\r\r\n')]
    patches += ['', 'not patch', '*** Begin Patch',patch('*** Environment ID: secret'),patch('*** Add File: a','bad'),patch('*** Update File: a'),patch('*** Update File: a','@@'),patch('*** Update File: a','@@','@@'),patch('*** Update File: a','@@','*** End of File'),patch('*** Update File: a','+body','*** End of File','+invalid'),patch('*** Update File: a','*** Move to: b','*** Move to: c'),patch('*** End Patch','+trailing'), '\ufeff'+patch(), '\x1c'+patch(),patch(' *** Update File: a','+body'),patch('*** Update File: a','@@','*** Update File: b','+body')]
    cases=[dict(kind='parse',patch=value) for value in patches]
    texts=['','a','a\n','a\n\n',' a \n','x\na\na\n','a\u0085\n','a\ufeff\n','a\x1c\n','\u201cdash\u201d\u2014\n','\u6d4b\U0001f9ea\n']
    def hunk(old,new,**extra):return dict(lineNumber=7,oldLines=old,newLines=new,isEndOfFile=False,**extra)
    for before in texts:
        for old in ('a',' a ','a\u0085','a\ufeff','"dash"-','missing',''):
            for eof in (False,True):
                value=hunk([old],['replacement']);value['isEndOfFile']=eof;cases.append(dict(kind='apply',before=before,hunks=[value]))
    cases += [dict(kind='apply',before=before,hunks=hunks) for before,hunks in [
        ('a\nb\na\n',[hunk(['a'],['first']),hunk(['a'],['last'])]),
        ('a\nb\n',[hunk(['b'],['B']),dict(hunk(['a'],['A']),isEndOfFile=True)]),
        ('a\n',[hunk([],['first']),hunk([],['second'])]),
        ('a\n',[hunk(['a'],['A']),hunk(['a'],['B'])]),
        ('a\n',[hunk(['a',''],['A',''])]),
        ('a\n',[dict(hunk(['a'],['A']),context='missing')]),
        ('anchor\na\n',[dict(hunk(['a'],['A']),context='anchor')]),
        ('first\nanchor\na\n',[hunk(['first'],['FIRST']),dict(hunk(['a'],['A']),context='anchor')]),
        ('\n\n',[hunk([],['insert'])]),('',[]),('unterminated',[])]]
    return cases


async def observe():
    from dsh.fs.patch import parse_patch,apply_hunks,PatchParseError
    rows=[]
    for index,case in enumerate(corpus()):
        try:rows.append(dict(index=index,kind=case['kind'],value=parse_patch(case['patch']) if case['kind']=='parse' else apply_hunks(case['before'],case['hunks'])))
        except PatchParseError as error:rows.append(dict(index=index,kind=case['kind'],error=dict(name=error.name,lineNumber=error.lineNumber,reason=error.reason,message=error.message)))
    return rows


def prepare(output):
    path=output/'corpus.json';path.write_text(json.dumps(corpus(),ensure_ascii=True),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_fs_patch.mts','Pure actual patch parser/updater: original line diagnostics, wrappers, CRLF/double CR, operation order and move headers, implicit/explicit hunks, EOF syntax, unsupported environment routing, Unicode White_Space versus BOM/control characters, four ordered match passes, EOF cursor override, original-text searches, stable insertion order, trailing blank sentinel and final LF. Corpus shared with unchanged Source.',[Path(__file__).resolve(),ROOT/'dsh/fs/patch/__init__.py',ROOT/'dsh/fs/patch/LICENSE'],prepare=prepare)
