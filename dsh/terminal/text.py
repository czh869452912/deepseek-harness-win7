"""Bounded line output and split-sequence terminal control sanitization."""


def utf8_tail(text, maximum):
    raw = text.encode('utf-8')
    if len(raw) <= maximum:
        return text, False
    return raw[-maximum:].decode('utf-8', errors='ignore'), True


class BoundedTextBuffer:
    def __init__(self, max_bytes, max_lines=None):
        self.max_bytes, self.max_lines = max_bytes, max_lines
        self.value, self.dropped = '', False

    def append(self, text):
        if not text:
            return
        self.value += text
        if self.max_lines is not None:
            lines = self.value.split('\n')
            if len(lines) > self.max_lines:
                self.value = '\n'.join(lines[-self.max_lines:])
                self.dropped = True
        self.value, dropped = utf8_tail(self.value, self.max_bytes)
        self.dropped = self.dropped or dropped

    def consume(self):
        result = dict(delta=self.value, truncated=self.dropped)
        self.value, self.dropped = '', False
        return result

    def snapshot(self):
        return dict(text=self.value, truncated=self.dropped)


class TerminalSanitizer:
    def __init__(self, max_pending_bytes):
        self.maximum = max_pending_bytes
        self.state, self.pending = 'text', ''
        self.pending_bytes = 0
        self.osc_escape = self.tracking_tail = self.trailing_cr = False

    def normalize(self, text):
        if self.trailing_cr:
            text = '\r' + text
        self.trailing_cr = text.endswith('\r')
        if self.trailing_cr:
            text = text[:-1]
        return text.replace('\r\n', '\n').replace('\r', '\n').replace('\x07', '')

    def push(self, chunk):
        output, tail = [], []
        prompt = False
        include_tail = self.tracking_tail
        for char in chunk:
            if self.state == 'text':
                if char == '\x1b':
                    self.state = 'escape'
                else:
                    output.append(char)
                    if self.tracking_tail:
                        tail.append(char)
            elif self.state == 'escape':
                self.state = 'osc' if char == ']' else 'csi' if char == '[' else 'text'
                self.pending, self.pending_bytes = '', 2
                self.osc_escape = False
            elif self.state == 'csi':
                if '\x40' <= char <= '\x7e':
                    self.state = 'text'
            elif self.state in ('osc', 'discard-osc'):
                ended = char == '\x07' or self.osc_escape and char == '\\'
                if ended:
                    if self.state == 'osc' and self.pending.startswith('133;D;'):
                        prompt = self.tracking_tail = include_tail = True
                        tail = []
                    self.state, self.pending, self.osc_escape = 'text', '', False
                else:
                    self.osc_escape = char == '\x1b'
                    if self.state == 'osc':
                        self.pending_bytes += len(char.encode('utf-8'))
                        if self.pending_bytes > self.maximum:
                            self.pending, self.state = '', 'discard-osc'
                        else:
                            self.pending += char
        result = dict(text=self.normalize(''.join(output)), prompt=prompt)
        if include_tail:
            result['promptTail'] = ''.join(tail)
        return result

    def flush(self):
        self.state, self.pending = 'text', ''
        self.tracking_tail = self.osc_escape = False
        result = '\n' if self.trailing_cr else ''
        self.trailing_cr = False
        return result
