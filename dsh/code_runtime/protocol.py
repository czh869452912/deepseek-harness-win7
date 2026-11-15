"""Bounded JSON lines and traffic ownership for the Python PTC transport."""
import json
import threading

from dsh.code_runtime.contract import encoded


class ProtocolError(ValueError):
    pass


class ControlClosedError(EOFError):
    pass


class JsonLines:
    def __init__(self, maximum):
        self.maximum = maximum
        self.partial = bytearray()

    def feed(self, chunk, receive):
        start = 0
        while start < len(chunk):
            end = chunk.find(b'\n', start)
            part = chunk[start:] if end == -1 else chunk[start:end]
            if not self.partial and part and part[0] != 0x7b:
                raise ProtocolError('control message is not a JSON object; the program bootstrap may be from another release')
            if len(self.partial) + len(part) > self.maximum:
                raise ProtocolError('RPC message exceeds %s bytes' % self.maximum)
            self.partial.extend(part)
            if end == -1:
                return
            size = len(self.partial)
            try:
                # Node replaces malformed UTF-8 before JSON parsing.
                value = json.loads(self.partial.decode('utf-8', errors='replace'),
                                   parse_constant=self._invalid_constant)
            except (ValueError, RecursionError) as error:
                raise ProtocolError('invalid control JSON: %s' % error)
            self.partial.clear()
            if not isinstance(value, dict):
                raise ProtocolError('control message is not a JSON object')
            receive(value, size)
            start = end + 1

    @staticmethod
    def _invalid_constant(value):
        raise ValueError('invalid JSON constant ' + value)

    def end(self):
        if self.partial:
            raise ProtocolError('incomplete RPC message')
        raise ControlClosedError('control channel ended before the program settled')


class QueuedBytes:
    """Charge the complete encoded line until its write finishes or fails."""
    def __init__(self, maximum):
        self.maximum = maximum
        self.size = 0

    def admit(self, value):
        line = encoded(value) + b'\n'
        if self.size + len(line) > self.maximum:
            raise ProtocolError('control output exceeds %s queued bytes' % self.maximum)
        self.size += len(line)
        return line

    def release(self, line):
        self.size -= len(line)


class PendingCalls:
    def __init__(self, maximum_calls, maximum_bytes):
        self.maximum_calls, self.maximum_bytes = maximum_calls, maximum_bytes
        self.count = self.size = 0

    def admit(self, args):
        size = len(encoded(args))
        if self.count >= self.maximum_calls or self.size + size > self.maximum_bytes:
            raise ProtocolError('pending binding calls exceed configured limits')
        self.count += 1
        self.size += size
        return size

    def release(self, size):
        self.count -= 1
        self.size -= size


class IncomingBytes:
    """Bound the reader-thread handoff as well as individual JSON frames."""
    def __init__(self, maximum):
        self.maximum, self.size = maximum, 0
        self.changed = threading.Condition()

    def admit(self, size, stopped):
        with self.changed:
            while self.size + size > self.maximum:
                if stopped.is_set():
                    return False
                self.changed.wait(.025)
            if stopped.is_set():
                return False
            self.size += size
            return True

    def release(self, size):
        with self.changed:
            self.size -= size
            self.changed.notify_all()
