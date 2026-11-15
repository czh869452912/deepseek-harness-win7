import copy

import pytest

from dsh.fs.patch import parse_patch,apply_hunks,PatchParseError
from scripts.rc022_fs_patch_probe import observe,corpus


def patch(*lines):return '\n'.join(['*** Begin Patch']+list(lines)+['*** End Patch'])


@pytest.mark.asyncio
async def test_shared_patch_corpus_has_failures_and_successful_unicode_updates():
    rows=await observe()
    assert len(rows)==len(corpus()) and len(rows)>190
    assert any(row.get('error',{}).get('lineNumber')==1 for row in rows)
    assert any(row.get('value',{}).get('ok') is False for row in rows if row['kind']=='apply')
    assert any(row.get('value',{}).get('after')=='replacement\n' for row in rows if row['kind']=='apply')


def test_original_input_line_numbers_and_file_order_survive_heredoc():
    value="\n\u0085\n<<'EOF'\n"+patch('*** Add File: a','+hello','*** Update File: a','*** Move to: b','@@','-hello','+hi','*** Delete File: a')+'\nEOF\n'
    operations=parse_patch(value)
    assert [(operation['kind'],operation['path'],operation['lineNumber']) for operation in operations]==[('add','a',5),('update','a',7),('delete','a',12)]
    assert operations[1]['moveTo']=='b' and operations[1]['hunks'][0]['lineNumber']==9
    with pytest.raises(PatchParseError) as error:parse_patch('\n\n'+patch('*** Update File: a','@@','@@'))
    assert error.value.lineNumber==6


def test_no_partial_text_or_input_mutation_when_later_hunk_does_not_match():
    hunks=parse_patch(patch('*** Update File: a','@@','-first','+FIRST','@@','-absent','+new'))[0]['hunks'];snapshot=copy.deepcopy(hunks)
    result=apply_hunks('first\nlast\n',hunks)
    assert result==dict(ok=False,failure=dict(hunkLineNumber=6,stage='oldLines',searchStart=1,pattern=['absent']))
    assert hunks==snapshot and 'after' not in result


def test_eof_can_search_before_cursor_and_insertions_keep_patch_order():
    hunks=parse_patch(patch('*** Update File: a','@@','-b','+B','@@','-a','+A','*** End of File'))[0]['hunks']
    # EOF selects only the tail, even when the cursor already passed it.
    assert not apply_hunks('a\nb\n',hunks)['ok']
    hunks=parse_patch(patch('*** Update File: a','@@','-a','+A','*** End of File','@@','-a','+AA','*** End of File'))[0]['hunks']
    assert apply_hunks('a\n',hunks)==dict(ok=True,after='A\n')
    insert=[dict(lineNumber=index,oldLines=[],newLines=[text],isEndOfFile=False) for index,text in enumerate(('first','second'))]
    assert apply_hunks('a\n',insert)==dict(ok=True,after='a\nfirst\nsecond\n')


@pytest.mark.parametrize('prefix',['\ufeff','\x1c'])
def test_non_unicode_white_space_is_not_silently_trimmed(prefix):
    with pytest.raises(PatchParseError):parse_patch(prefix+patch())
