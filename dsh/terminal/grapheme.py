"""Unicode 16 extended grapheme clusters (UAX #29 revision 45)."""
from bisect import bisect_right
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def tables():
    data=json.loads((Path(__file__).parent/'unicode16/grapheme.json').read_text(encoding='utf-8'))
    return {key:([row[0] for row in rows],rows) for key,rows in data.items()}


@lru_cache(maxsize=4096)
def property_of(code, table):
    if table=='gcb' and 0xac00<=code<=0xd7a3:return 'LV' if (code-0xac00)%28==0 else 'LVT'
    starts,rows=tables()[table];index=bisect_right(starts,code)-1
    return rows[index][2] if index>=0 and code<=rows[index][1] else 'Other'


def utf8(text):
    return text.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')


def segments(text):
    # Join explicitly represented UTF-16 pairs, retaining lone surrogates as JS does.
    text=text.encode('utf-16-le','surrogatepass').decode('utf-16-le','surrogatepass')
    if not text:return []
    codes=[ord(character) for character in text]
    gcb=[property_of(code,'gcb') for code in codes];incb=[property_of(code,'incb') for code in codes]
    pictographic=[property_of(code,'pictographic')!='Other' for code in codes]
    starts=[0];ri_count=1 if gcb[0]=='Regional_Indicator' else 0
    for index in range(1,len(text)):
        left,right=gcb[index-1:index+1];boundary=True
        if left=='CR' and right=='LF':boundary=False # GB3
        elif left in ('Control','CR','LF') or right in ('Control','CR','LF'):pass # GB4/5
        elif left=='L' and right in ('L','V','LV','LVT'):boundary=False # GB6
        elif left in ('LV','V') and right in ('V','T'):boundary=False # GB7
        elif left in ('LVT','T') and right=='T':boundary=False # GB8
        elif right in ('Extend','ZWJ','SpacingMark') or left=='Prepend':boundary=False # GB9/9a/9b
        else:
            if incb[index]=='Consonant': # GB9c
                cursor=index-1;linker=False
                while cursor>=0 and incb[cursor] in ('Extend','Linker'):
                    linker=linker or incb[cursor]=='Linker';cursor-=1
                if linker and cursor>=0 and incb[cursor]=='Consonant':boundary=False
            if boundary and pictographic[index] and left=='ZWJ': # GB11
                cursor=index-2
                while cursor>=0 and gcb[cursor]=='Extend':cursor-=1
                if cursor>=0 and pictographic[cursor]:boundary=False
            if left==right=='Regional_Indicator' and ri_count%2==1:boundary=False # GB12/13
        if boundary:starts.append(index)
        ri_count=ri_count+1 if right=='Regional_Indicator' else 0
    starts.append(len(text))
    return [text[start:end] for start,end in zip(starts,starts[1:])]


def tail_within(text,maximum):
    graphemes=segments(text);size=0;start=len(graphemes)
    while start>0:
        following=len(utf8(graphemes[start-1]))
        if size+following>maximum:break
        size+=following;start-=1
    return ''.join(graphemes[start:])
