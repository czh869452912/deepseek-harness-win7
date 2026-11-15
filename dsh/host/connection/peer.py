"""One creator-owned party admitted to the Host, with a fixed principal."""
import uuid
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope
from dsh.cordis.awaiting import start_coroutine


class Peer:
    def __init__(self, owner, options):
        self.id = str(uuid.uuid4())
        self.principal = options['principal']
        self.interactions = 'answer' if options.get('interactions') is None else options['interactions']
        self.scope = create_scope(owner, self)
        self.ctx = self.scope.ctx
        lifetime = AbortController()
        self.signal = lifetime.signal
        self._disposing = None
        self.ctx.effect(lambda: lambda: lifetime.abort(RuntimeError('Peer %s was disposed' % self.id)), 'client-connection: Peer lifetime')

    def dispose(self):
        if self._disposing is None:
            self._disposing = start_coroutine(self.scope.dispose())
        return self._disposing
