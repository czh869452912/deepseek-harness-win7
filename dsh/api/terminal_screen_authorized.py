"""Plain-text screen projection over dense xterm buffer rows and grapheme-safe pages."""
from dsh.terminal.grapheme import tail_within,utf8

JS_WHITESPACE='\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def last_content_row(buffer):
    row=len(buffer['lines'])-1;cursor=buffer['baseY']+buffer['cursorY']
    while row>cursor and buffer['lines'][row]['trimmed']=='':row-=1
    return row


def cursor_line_start(buffer):
    row=buffer['baseY']+buffer['cursorY']
    while row>0 and buffer['lines'][row]['isWrapped']:row-=1
    return row


def render_lines(buffer,start,end):
    lines=[];current=None
    for row in range(max(0,start),min(end,len(buffer['lines']))):
        line=buffer['lines'][row]
        if current is not None and line['isWrapped']:current+=line['text'];continue
        if current is not None:lines.append(current.rstrip(JS_WHITESPACE))
        current=line['text']
    if current is not None:lines.append(current.rstrip(JS_WHITESPACE))
    return lines


def page_lines(lines,request):
    end=max(0,len(lines)-request['offset']);begin=max(0,end-request['count']);selected=lines[begin:end]
    size=0;first=len(selected)
    while first>0:
        following=len(utf8(selected[first-1]))+(0 if first==len(selected) else 1)
        if size+following>request['maxBytes']:break
        size+=following;first-=1
    kept=selected[first:];truncated=first>0
    if not kept and selected:kept.append(tail_within(selected[-1],request['maxBytes']));truncated=True
    return dict(text='\n'.join(kept),totalLines=len(lines),lineBegin=request['offset'],lineEnd=request['offset']+len(kept),truncated=truncated)
