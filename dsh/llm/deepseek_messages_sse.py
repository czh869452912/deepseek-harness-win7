"""Incremental eventsource-parser-compatible Messages framing over owned byte input."""
import codecs

from dsh.llm.deepseek_messages_errors import providerError
from dsh.llm.deepseek_messages_replay import object_value
from dsh.llm.llm_service import LlmError
from dsh.llm.pi_json import loads


class _Frames:
    def __init__(self, activity):
        self.activity,self.buffer,self.first,self.data,self.event = activity,'',True,[],None

    def feed(self, text):
        if not text: return []
        if self.first:
            self.first = False
            if text.startswith('\u00ef\u00bb\u00bf'): text = text[3:]
        # eventsource-parser 3.1 keeps pending fragments until the incoming
        # fragment itself contains a delimiter, even when a prior one ended CR.
        if self.buffer and '\r' not in text and '\n' not in text:
            self.buffer += text
            return []
        self.buffer += text
        frames,position = [],0
        while position < len(self.buffer):
            cr,lf = self.buffer.find('\r',position),self.buffer.find('\n',position)
            ends = [value for value in (cr,lf) if value >= 0]
            if not ends: break
            end = min(ends)
            if self.buffer[end] == '\r' and end == len(self.buffer)-1: break
            line = self.buffer[position:end]
            position = end+1
            if self.buffer[end] == '\r' and self.buffer[position:position+1] == '\n': position += 1
            if not line:
                if self.data: frames.append((self.event,'\n'.join(self.data)))
                self.data,self.event = [],None
            elif line.startswith(':'): self.activity()
            else:
                field,separator,value = line.partition(':')
                if value.startswith(' '): value = value[1:]
                if field == 'data': self.data.append(value)
                elif field == 'event': self.event = value or None
        self.buffer = self.buffer[position:]
        return frames


async def parseSse(body, activity):
    decoder,parser = codecs.getincrementaldecoder('utf-8-sig')('replace'),_Frames(activity)
    def decode(frames):
        for name,data in frames:
            activity()
            try: raw = loads(data)
            except Exception as error: raise LlmError('DeepSeek Messages SSE contains invalid JSON','MALFORMED_RESPONSE') from error
            event = object_value(raw)
            if not isinstance(event.get('type'),str) or name is not None and name != event['type']:
                raise LlmError('DeepSeek Messages SSE event type mismatch','MALFORMED_RESPONSE')
            if event['type'] == 'error': raise providerError(event)
            yield event
    iterator = body.__aiter__()
    try:
        async for chunk in iterator:
            for event in decode(parser.feed(decoder.decode(chunk))): yield event
        for event in decode(parser.feed(decoder.decode(b'',final=True))): yield event
    finally:
        close = getattr(iterator,'aclose',None)
        if close is not None: await close()
