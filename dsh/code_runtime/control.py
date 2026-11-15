"""Per-process authenticated loopback control channel, including Windows 7.

The endpoint separates protocol traffic from inherited output descriptors.
It is not a security boundary against code executing inside the interpreter.
"""
import hmac
import secrets
import socket
import threading


class ControlListener:
    def __init__(self):
        self.lock = threading.Lock()
        self.closed = False
        self.connection = self.incoming = self.outgoing = None
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.listener.bind(('127.0.0.1', 0))
            self.listener.listen(8)
            self.listener.settimeout(.05)
            self.spec = dict(port=self.listener.getsockname()[1], token=secrets.token_hex(32))
        except BaseException:
            self.listener.close()
            raise

    def accept(self, stopped, exited):
        while not stopped.is_set() and not exited():
            try:
                connection, address = self.listener.accept()
            except socket.timeout:
                continue
            accepted = False
            try:
                connection.settimeout(.25)
                token = bytearray()
                while len(token) < 65:
                    value = connection.recv(1)
                    if not value or value == b'\n':
                        break
                    token.extend(value)
                if address[0] != '127.0.0.1' or not hmac.compare_digest(bytes(token), self.spec['token'].encode('ascii')):
                    continue
                connection.settimeout(None)
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self.lock:
                    if self.closed:
                        return None
                    self.connection = connection
                    # No BufferedReader lock may hold owner disposal behind a
                    # blocked Windows recv on another thread.
                    self.incoming = connection.makefile('rb', buffering=0)
                    self.outgoing = connection.makefile('wb')
                    accepted = True
                    self.listener.close()
                    return self.incoming
            except (OSError, ValueError):
                pass
            finally:
                if not accepted:
                    connection.close()
        return None

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.listener.close()
            if self.connection is not None:
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
            for stream in (self.incoming, self.outgoing):
                if stream is not None:
                    stream.close()


def connect_control(spec):
    connection = socket.create_connection(('127.0.0.1', spec['port']), timeout=5)
    connection.settimeout(None)
    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    incoming, outgoing = connection.makefile('rb'), connection.makefile('wb')
    outgoing.write(spec['token'].encode('ascii') + b'\n')
    outgoing.flush()
    return connection, incoming, outgoing
