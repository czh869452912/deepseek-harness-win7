"""Canonical shell service: bounded subprocess ownership and confinement facts."""
import asyncio
import errno
import math
import os
import shutil

from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.settings.provider import install_settings_section
from dsh.subprocess.local import _signal_aborted
from dsh.subprocess.types import SubprocessCollect, SubprocessSpawnSpec, SubprocessStdio
from dsh.sandbox.vocabulary import SandboxUnavailableError


DEFAULTS = dict(timeoutMs=120000, maxTimeoutMs=600000, maxOutputBytes=64000,
                maxSpillBytes=64 * 1024 * 1024, graceMs=3000)
PREAMBLE = "if ($ExecutionContext.SessionState.LanguageMode -eq 'FullLanguage') { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; $OutputEncoding = New-Object System.Text.UTF8Encoding $false }; "


def positive(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError("pwsh-local: {} must be a positive finite number".format(name))


def validate_config(config):
    for name in DEFAULTS:
        positive(name, config[name])
    if config['graceMs'] > 2147483647:
        raise ValueError('pwsh-local: graceMs exceeds timer bound')


def runner_failure(code, stderr, rules):
    if code is None or code == 0:
        return None
    for rule in rules:
        if 'allowedExitCodes' in rule and code not in rule['allowedExitCodes']:
            continue
        ignored = [line.lower() for line in rule.get('informationalLines', [])]
        for line in stderr.splitlines():
            if line.lower() in ignored:
                continue
            if any(s.strip() and s.lower() in line.lower() for s in rule['fatalSignatures']):
                return line
    return None


def spawn_runner_failure(error, program, cwd):
    # Python Popen identifies the failed executable via filename on POSIX;
    # Windows omits it. A usable cwd independently excludes the other source.
    return (isinstance(error, OSError) and error.errno in (errno.ENOENT, errno.EACCES)
            and os.path.isdir(cwd) and os.access(cwd, os.X_OK)
            and (error.filename == program or (os.name == 'nt' and error.filename is None)))


def final_output(reader):
    value = reader.read_from(0)
    result = dict(text=value.text, truncated=value.lossy)
    if value.spillPath is not None:
        result['spillPath'] = value.spillPath
    return result


class ShellProcess:
    def __init__(self, handle, spec, facts):
        self.handle, self.spec, self.facts = handle, spec, facts
        self.status, self.exitCode, self.signal = 'running', None, None
        self.sandbox = None
        self.offsets = [0, 0]
        self.spawn_note = ''
        self.done = asyncio.create_task(self._settle())

    async def _settle(self):
        failed = False
        try:
            outcome = await self.handle.done
            self.exitCode, self.signal = outcome.exitCode, outcome.signal
            if self.status == 'running':
                self.status = 'killed' if _signal_aborted(self.spec.get('signal')) or outcome.signal else 'completed'
        except Exception as error:
            self.status = 'killed'
            self.spawn_note = 'spawn failed: {}'.format(error)
            failed = bool(self.facts and spawn_runner_failure(error, self.facts['argv'][0], self.spec['workdir']))
        if self.facts:
            stderr = self.handle.collected.stderr.read_from(0).text
            self.sandbox = sandbox_info(self.spec, self.facts, self.exitCode, stderr, failed)

    def kill(self):
        if self.status != 'running':
            return False
        self.status = 'killed'
        self.handle.terminate()
        return True

    def readOutput(self):
        values = []
        result = dict(lossy=False)
        for index, name in enumerate(('stdout', 'stderr')):
            value = getattr(self.handle.collected, name).read_from(self.offsets[index])
            self.offsets[index] = value.nextOffset
            result['lossy'] |= value.lossy
            if value.spillPath:
                result[name + 'SpillPath'] = value.spillPath
            values.append(value.text)
        if not values[1]:
            values[1], self.spawn_note = self.spawn_note, ''
        result['delta'] = values[0]
        if values[1]:
            result['delta'] += ('\n' if values[0] and not values[0].endswith('\n') else '') + '[stderr]\n' + values[1]
        return result


def sandbox_info(spec, facts, code, stderr, failed=False):
    failed = failed or runner_failure(code, stderr, facts['runnerFailureRules']) is not None
    result = dict(mode=spec['sandboxPolicy']['mode'], enforcement=facts['enforcement'],
                  denied=not failed and code not in (None, 0) and any(s.lower() in stderr.lower() for s in facts['denialSignatures']))
    if failed:
        result['runnerFailed'] = True
    return result


class PwshLocalExecutor(Service):
    inject = ['subprocess']
    Config = Schema.object(dict({name: Schema.number().default(value) for name, value in DEFAULTS.items()},
                                cwd=Schema.string(), pwshPath=Schema.string()))

    def __init__(self, ctx, config=None):
        entry = dict(DEFAULTS, **(config or {}))
        validate_config(entry)
        self.source = lambda: entry
        super().__init__(ctx, 'shell')
        install_settings_section(ctx, 'shell', self.Config, entry,
            dict(setSource=lambda source: setattr(self, 'source', source), validate=validate_config, onChange=lambda: None))

    def apply(self, ctx=None, config=None):
        pass

    @property
    def sandboxMode(self):
        return None

    def resolve(self, request):
        config = self.source()
        timeout = request.get('timeoutMs', config['timeoutMs'])
        cap = request.get('stdoutMaxBytes', config['maxOutputBytes'])
        positive('request.timeoutMs', timeout)
        positive('request.stdoutMaxBytes', cap)
        result = dict(request)
        result.update(workdir=request.get('workdir') or config.get('cwd') or os.getcwd(),
                      timeoutMs=min(timeout, config['maxTimeoutMs']), stdoutMaxBytes=cap)
        return result

    def argv(self, spec):
        configured = self.source().get('pwshPath')
        # Windows PowerShell is the supported Win7 runtime; modern pwsh is optional.
        program = configured or shutil.which('powershell.exe') or shutil.which('pwsh') or 'powershell.exe'
        return [program, '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', PREAMBLE + spec['command']]

    def wrap(self, spec):
        return self.argv(spec), None

    def spawn(self, spec, argv, background=False):
        config = self.source()
        env = dict(NO_COLOR='1', PAGER='cat', GIT_PAGER='cat')
        env.update(spec.get('env') or {})
        env.update(spec.get('dshEnv') or {})
        collect = lambda size: SubprocessCollect(int(size), {'maxBytes': int(config['maxSpillBytes'])})
        return self.ctx.get('subprocess').spawn(SubprocessSpawnSpec(
            argv=argv, cwd=spec['workdir'], grace_ms=config['graceMs'], signal=spec.get('signal'), env=env,
            stdio=SubprocessStdio({'data': spec['stdin']} if 'stdin' in spec else 'ignore',
                                 collect(config['maxOutputBytes'] if background else spec['stdoutMaxBytes']),
                                 collect(config['maxOutputBytes']))))

    async def run(self, spec):
        argv, facts = self.wrap(spec)
        handle = None
        timed_out = False
        try:
            handle = self.spawn(spec, argv)
            try:
                outcome = await asyncio.wait_for(asyncio.shield(handle.done), spec['timeoutMs'] / 1000)
            except asyncio.TimeoutError:
                timed_out = not _signal_aborted(spec.get('signal'))
                handle.terminate()
                outcome = await asyncio.shield(handle.done)
        except asyncio.CancelledError:
            if handle is not None:
                handle.terminate()
                await asyncio.shield(handle.done)
            raise
        except Exception as error:
            if facts and not _signal_aborted(spec.get('signal')) and spawn_runner_failure(error, argv[0], spec['workdir']):
                raise SandboxUnavailableError(spec['sandboxPolicy']['mode'], str(error)) from error
            raise
        result = dict(exitCode=outcome.exitCode, signal=outcome.signal, timedOut=timed_out,
                      aborted=_signal_aborted(spec.get('signal')) and not timed_out, timeoutMs=spec['timeoutMs'],
                      stdout=final_output(handle.collected.stdout), stderr=final_output(handle.collected.stderr))
        if facts:
            fatal = runner_failure(outcome.exitCode, result['stderr']['text'], facts['runnerFailureRules'])
            if fatal is not None:
                raise SandboxUnavailableError(spec['sandboxPolicy']['mode'], fatal)
            result['sandbox'] = sandbox_info(spec, facts, outcome.exitCode, result['stderr']['text'])
        elif 'sandboxPolicy' in spec:
            result['sandbox'] = dict(mode=spec['sandboxPolicy']['mode'], denied=False)
        return result

    def start(self, spec):
        argv, facts = self.wrap(spec)
        try:
            handle = self.spawn(spec, argv, background=True)
        except Exception as error:
            if facts and spawn_runner_failure(error, argv[0], spec['workdir']):
                raise SandboxUnavailableError(spec['sandboxPolicy']['mode'], str(error)) from error
            raise
        return ShellProcess(handle, spec, facts)


class SandboxPwshExecutor(PwshLocalExecutor):
    inject = ['subprocess', 'sandbox', 'sandboxPolicy']

    @property
    def sandboxMode(self):
        return self.ctx.get('sandboxPolicy').defaultMode

    def resolve(self, request):
        result = super().resolve(request)
        result['sandboxPolicy'] = request.get('sandboxPolicy') or self.ctx.get('sandboxPolicy').resolve()
        return result

    def wrap(self, spec):
        argv = self.argv(spec)
        if spec['sandboxPolicy']['mode'] == 'danger-full-access':
            return argv, None
        facts = self.ctx.get('sandbox').confine(argv, spec['sandboxPolicy'])
        return facts['argv'], facts
