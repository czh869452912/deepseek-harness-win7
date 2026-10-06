"""Persistent Windows console backend over canonical sandbox/subprocess seams."""
import asyncio
import os
import shutil
import sys
import time
import uuid
import weakref

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.sandbox.sandbox_policy import effective_sandbox_mode
from dsh.subprocess.types import SubprocessTerminalSpawnSpec
from dsh.terminal.service import TerminalBackendCleanupError, check_signal
from dsh.terminal.session import LocalTerminalSession


DEFAULTS = dict(backendType='shell', shellDialect='bash', rows=40, cols=160, scrollbackLines=10000,
    scrollbackMaxBytes=4 * 1024 * 1024, maxReadBytes=256 * 1024, pollIntervalMs=50,
    exactProbeAfterMs=150, idleSilenceMs=3000, handoffGraceMs=500, timeoutMs=30000, disposeGraceMs=3000)

_fenced_owners = weakref.WeakSet()


class LocalTerminalBackend:
    def __init__(self, ctx, config):
        self.ctx, self.config = ctx, config
        self.type = config['backendType']

    def fence(self, owner):
        if owner in _fenced_owners:
            return
        def check(mode, name, args, caller_ctx=None):
            if name != 'session/event' or len(args) < 2 or args[0] is not owner.session:
                return
            event = args[1]
            if event['type'] != 'sandbox/mode':
                return
            policy, terminals = owner.ctx.get('sandboxPolicy'), owner.ctx.get('terminals')
            if policy is None or terminals is None:
                return
            current = effective_sandbox_mode(owner.session.events) or policy.defaultMode
            if event['data']['mode'] != current and terminals.hasOwnerActivity(owner):
                raise RuntimeError('cannot change sandbox mode while persistent terminal sessions are open or being created')
        owner.ctx.on('internal/dispatch', check, global_listener=True)
        _fenced_owners.add(owner)

    async def spawn(self, spec):
        if sys.platform != 'win32':
            raise RuntimeError('this portable terminal backend currently requires Windows WinPTY')
        check_signal(spec.get('signal'))
        self.fence(spec['owner'])
        config = self.config
        policy = self.ctx.get('sandboxPolicy').resolve({'session': spec['owner'].session})
        argv = [config['shellPath']] + config['shellArgs']
        if policy['mode'] != 'danger-full-access':
            sandbox = self.ctx.get('sandbox')
            if sandbox is None:
                raise RuntimeError('confined terminal requires ctx.sandbox')
            argv = sandbox.confine(argv, policy)['argv']
        env = dict(TERM='dumb', PAGER='cat', GIT_PAGER='cat', DSH_SHELL='1',
                   DSH_SESSION_ID=str(spec['owner'].id), DSH_PTY_SESSION_ID=spec['sessionId'], NO_COLOR='1')
        terminal = await self.ctx.get('subprocess').spawn_terminal(SubprocessTerminalSpawnSpec(
            argv, spec.get('cwd', policy['workspaceRoot']), config['rows'], config['cols'], config['disposeGraceMs'], env, spec.get('signal')))
        session = LocalTerminalSession(terminal, config)
        try:
            # Silence is not proof of initialization: require a fresh nonce on
            # its own output line, which cannot be satisfied by the input echo.
            marker = '__DSH_READY_{}__'.format(uuid.uuid4().hex)
            setup = ("if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { exit 1 }; "
                     "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; $OutputEncoding = [Console]::OutputEncoding; "
                     "function prompt { 'dsh> ' }; Write-Output ''; Write-Output '" + marker + "'") if config['shellDialect'] == 'pwsh' else "PS1='dsh> '; unset PROMPT_COMMAND; printf '\\n%s\\n' '" + marker + "'"
            expires = time.monotonic() + config['timeoutMs'] / 1000
            first = True
            while True:
                result = await session.startSend(dict(text=setup if first else '', submit=first, signal=spec.get('signal'))).done
                first = False
                check_signal(spec.get('signal'))
                if result['waitReason'] in ('timeout', 'session_exit') or time.monotonic() >= expires:
                    raise RuntimeError('terminal shell failed to reach startup readiness')
                if '\n' + marker + '\n' in session.read(dict(count=config['scrollbackLines']))['text']:
                    break
            session.motd = session.read()['text']
            return session
        except BaseException as error:
            try:
                await session.close('PTY startup failed')
            except Exception as cleanup:
                raise TerminalBackendCleanupError(error, cleanup)
            raise


class LocalTerminalPlugin(Plugin):
    id = 'terminal-bash'
    inject = ['terminals', 'sandboxPolicy', 'subprocess']
    Config = Schema.object(dict({name: Schema.number().default(value) for name, value in DEFAULTS.items() if type(value) is int},
        backendType=Schema.string().default('shell'), shellDialect=Schema.union(['bash', 'pwsh']).default('bash'),
        shellPath=Schema.string(), shellArgs=Schema.array(Schema.string())))

    def apply(self, ctx):
        config = dict(DEFAULTS, **self.config)
        for name, value in DEFAULTS.items():
            if type(value) is int and (type(config[name]) is not int or not 0 < config[name] <= 9007199254740991):
                raise ValueError('terminal-bash: {} must be a positive safe integer'.format(name))
        if not config['backendType'] or config['maxReadBytes'] > config['scrollbackMaxBytes'] or config['handoffGraceMs'] < config['pollIntervalMs']:
            raise ValueError('terminal-bash: invalid backend or composed bounds')
        dialect = config['shellDialect']
        if not config.get('shellPath'):
            config['shellPath'] = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe') if dialect == 'pwsh' else shutil.which('bash') or '/bin/bash'
        if not config.get('shellArgs'):
            config['shellArgs'] = ['-NoLogo', '-NoProfile'] if dialect == 'pwsh' else ['--noprofile', '--norc', '-i']
        ctx.get('terminals').registerBackend(LocalTerminalBackend(ctx, config))
