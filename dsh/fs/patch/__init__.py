"""Pure Codex-style batch patch parsing and NormalizeToLf text updates.

Ported from fixed DeepSeek fs-patch, adapting OpenAI Codex rust-v0.158.0.
Copyright 2025 OpenAI; Apache-2.0 portions and MIT contributions: LICENSE.
Modifications: Python 3.8 pure records, Unicode White_Space and structured failures.
"""
import re

WHITE_SPACE='\t\n\v\f\r \u0085\u00a0\u1680'+''.join(chr(value) for value in range(0x2000,0x200b))+'\u2028\u2029\u202f\u205f\u3000'
BEGIN='*** Begin Patch';END='*** End Patch';EOF='*** End of File'
MOVE='*** Move to: ';ADD='*** Add File: ';DELETE='*** Delete File: ';UPDATE='*** Update File: '


class PatchParseError(ValueError):
    name='PatchParseError'
    def __init__(self,line_number,reason):
        self.lineNumber=line_number;self.reason=reason;self.message='Invalid patch at line '+str(line_number)+': '+reason
        super().__init__(self.message)


def patch_lines(patch):
    leading=patch[:len(patch)-len(patch.lstrip(WHITE_SPACE))];offset=leading.count('\n')
    lines=[dict(text=text,number=offset+index+1) for index,text in enumerate(re.split(r'\r?\n',patch.strip(WHITE_SPACE)))]
    if lines[0]['text'] in ('<<EOF',"<<'EOF'",'<<"EOF"') and lines[-1]['text'].endswith('EOF') and len(lines)>=4:lines=lines[1:-1]
    if lines[0]['text'].strip(WHITE_SPACE)!=BEGIN:raise PatchParseError(lines[0]['number'],"Expected '"+BEGIN+"'")
    if lines[-1]['text'].strip(WHITE_SPACE)!=END:raise PatchParseError(lines[-1]['number'],"Expected '"+END+"'")
    return [dict(line,text=re.sub(r'\r$','',line['text'])) if index<len(lines)-1 else line for index,line in enumerate(lines)]


def empty_hunk(hunk):return not hunk['oldLines'] and not hunk['newLines']


def ensure_update(operation,line_number):
    if operation is None or operation['kind']!='update':return
    if not operation['hunks']:raise PatchParseError(operation['lineNumber'],"Update for '"+operation['path']+"' requires at least one hunk")
    if empty_hunk(operation['hunks'][-1]):raise PatchParseError(line_number,'Update hunk must contain context, added, or removed lines')


def new_hunk(line_number):return dict(lineNumber=line_number,oldLines=[],newLines=[],isEndOfFile=False)


def read_update(operation,line):
    text=line['text'].rstrip(WHITE_SPACE);previous=operation['hunks'][-1] if operation['hunks'] else None;marker=text=='@@' or text.startswith('@@ ')
    if previous is not None and previous['isEndOfFile']:
        if text=='':return
        if not marker:raise PatchParseError(line['number'],"Expected '@@' after '*** End of File'")
    if previous is None and 'moveTo' not in operation and text.startswith(MOVE):operation['moveTo']=text[len(MOVE):];return
    if marker:
        if previous is not None and empty_hunk(previous):raise PatchParseError(line['number'],'Update hunk must contain context, added, or removed lines')
        hunk=new_hunk(line['number'])
        if text.startswith('@@ '):hunk['context']=text[3:]
        operation['hunks'].append(hunk);return
    if text==EOF:
        if previous is not None:
            if empty_hunk(previous):raise PatchParseError(line['number'],'Update hunk must contain context, added, or removed lines')
            previous['isEndOfFile']=True
        return
    prefix=line['text'][:1]
    if line['text']!='' and prefix not in (' ','+','-'):raise PatchParseError(line['number'],"Expected a context (' '), added ('+'), removed ('-') line, or '@@'")
    hunk=previous if previous is not None else new_hunk(line['number'])
    if previous is None:operation['hunks'].append(hunk)
    content=line['text'][1:]
    if prefix=='+':hunk['newLines'].append(content)
    elif prefix=='-':hunk['oldLines'].append(content)
    else:hunk['oldLines'].append(content);hunk['newLines'].append(content)


def parse_patch(patch):
    lines=patch_lines(patch);operations=[];ended=False
    for index,line in enumerate(lines[1:],1):
        operation=operations[-1] if operations else None
        header=line['text'].rstrip(WHITE_SPACE) if operation is not None and operation['kind']=='update' and index!=len(lines)-1 else line['text'].strip(WHITE_SPACE)
        if ended and index!=len(lines)-1:
            if line['text'].strip(WHITE_SPACE)!='':raise PatchParseError(line['number'],"Unexpected content after '"+END+"'")
            continue
        if header==END:ensure_update(operation,line['number']);ended=True
        elif header.startswith(ADD):
            ensure_update(operation,line['number']);operations.append(dict(kind='add',path=header[len(ADD):],lineNumber=line['number'],content=''))
        elif header.startswith(DELETE):
            ensure_update(operation,line['number']);operations.append(dict(kind='delete',path=header[len(DELETE):],lineNumber=line['number']))
        elif header.startswith(UPDATE):
            ensure_update(operation,line['number']);operations.append(dict(kind='update',path=header[len(UPDATE):],lineNumber=line['number'],hunks=[]))
        elif not operations and header.startswith('*** Environment ID:'):raise PatchParseError(line['number'],'Environment ID headers are unsupported; the caller selects the filesystem provider')
        elif operation is not None and operation['kind']=='add' and line['text'].startswith('+'):operation['content']+=line['text'][1:]+'\n'
        elif operation is not None and operation['kind']=='update':read_update(operation,line)
        else:raise PatchParseError(line['number'],'Expected an Add File, Delete File, or Update File header; added content must start with +')
    return operations


def punctuation(value):
    value=value.strip(WHITE_SPACE)
    value=re.sub('[\u2010-\u2015\u2212]','-',value);value=re.sub('[\u2018-\u201b]',"'",value);value=re.sub('[\u201c-\u201f]','"',value)
    return re.sub('[\u00a0\u2002-\u200a\u202f\u205f\u3000]',' ',value)


MATCH_PASSES=(lambda value:value,lambda value:value.rstrip(WHITE_SPACE),lambda value:value.strip(WHITE_SPACE),punctuation)


def seek_sequence(lines,pattern,start,eof):
    if not pattern:return start
    if len(pattern)>len(lines):return None
    last=len(lines)-len(pattern);first=last if eof else start
    for normalize in MATCH_PASSES:
        expected=[normalize(line) for line in pattern]
        for index in range(first,last+1):
            if all(normalize(lines[index+offset])==line for offset,line in enumerate(expected)):return index
    return None


def apply_hunks(before,hunks):
    original=before.split('\n')
    if original[-1]=='':original.pop()
    replacements=[];line_index=0
    for hunk in hunks:
        if 'context' in hunk:
            pattern=[hunk['context']];found=seek_sequence(original,pattern,line_index,False)
            if found is None:return dict(ok=False,failure=dict(hunkLineNumber=hunk['lineNumber'],stage='context',searchStart=line_index,pattern=pattern))
            line_index=found+1
        if not hunk['oldLines']:
            start=len(original)-1 if original and original[-1]=='' else len(original)
            replacements.append(dict(start=start,oldLength=0,newLines=hunk['newLines']));continue
        pattern=hunk['oldLines'];new_lines=hunk['newLines'];found=seek_sequence(original,pattern,line_index,hunk['isEndOfFile'])
        if found is None and pattern and pattern[-1]=='':
            pattern=pattern[:-1]
            if new_lines and new_lines[-1]=='':new_lines=new_lines[:-1]
            found=seek_sequence(original,pattern,line_index,hunk['isEndOfFile'])
        if found is None:return dict(ok=False,failure=dict(hunkLineNumber=hunk['lineNumber'],stage='oldLines',searchStart=line_index,pattern=list(hunk['oldLines'])))
        replacements.append(dict(start=found,oldLength=len(pattern),newLines=new_lines));line_index=found+len(pattern)
    lines=original
    for replacement in reversed(sorted(replacements,key=lambda value:value['start'])):
        start=replacement['start'];lines=lines[:start]+list(replacement['newLines'])+lines[start+replacement['oldLength']:]
    if not lines or lines[-1]!='':lines.append('')
    return dict(ok=True,after='\n'.join(lines))


parsePatch=parse_patch
applyHunks=apply_hunks
