"""Absolute-byte job output ring with UTF-8-safe tail eviction."""
from dsh.terminal.grapheme import utf8


class OutputRing:
    def __init__(self):
        self.chunks=[]
        self.retainedBytes=self.total=self.earliest=0

    def append(self,text,options=None,cap=262144):
        if len(text)==0:return False
        size=len(utf8(text));entry=dict(at=self.total,text=text,bytes=size)
        if options is not None:
            for key in ('channel','gapBefore'):
                if key in options:entry[key]=options[key]
        self.chunks.append(entry);self.total+=size;self.retainedBytes+=size
        self.trim(cap);return True

    def trim(self,cap):
        while self.retainedBytes>cap and len(self.chunks)>1:
            self.retainedBytes-=self.chunks.pop(0)['bytes']
        if len(self.chunks)==1 and self.chunks[0]['bytes']>cap:
            entry=self.chunks[0];raw=utf8(entry['text']);start=len(raw)-cap
            while start<len(raw) and raw[start]&0xc0==0x80:start+=1
            tail=raw[start:];entry['at']+=entry['bytes']-len(tail)
            entry.update(text=tail.decode('utf-8'),bytes=len(tail),gapBefore=True)
            self.retainedBytes=len(tail)
        self.earliest=self.chunks[0]['at'] if self.chunks else self.total

    def readFrom(self,offset):
        return dict(chunks=[{key:value for key,value in entry.items() if key!='bytes'}
                            for entry in self.chunks if entry['at']+entry['bytes']>offset],
                    next=self.total,lossy=offset<self.earliest)
