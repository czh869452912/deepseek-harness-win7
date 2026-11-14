"""Settled Loader startup policy and bounded, configuration-free diagnostics."""
import asyncio
import sys
from typing import Any, Dict, List, Optional

from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.errors import AggregateError, safe_string
from dsh.cordis.fiber import FiberState
from dsh.cordis.utils import get_isolate_symbol


REQUIRED_STARTUP_ENTRY_IDS = frozenset((
    'agent-loop', 'tool-executor-native', 'tool-executor-ptc', 'webserver',
    'web-runtime', 'modules', 'connection', 'headless-runner', 'acp', 'sdk-jsonrpc-server',
))
STATE_NAMES = {0: 'pending', 1: 'loading', 2: 'active', 3: 'failed', 4: 'disposed', 5: 'unloading'}


class StartupError(RuntimeError):
    """A startup audit failure retaining original causes and entry metadata."""
    def __init__(self, message: str, entries: List[Dict[str, Any]]):
        super().__init__(message)
        self.entries = entries
        self.composition: Optional[Dict[str, Any]] = None
        self.startup: Optional[Dict[str, Any]] = None
        failures = [row['outcome']['error'] for row in entries if row['outcome']['kind'] == 'failed']
        if failures:
            self.__cause__ = AggregateError(failures, 'Plugin activation failures')
            self.cause = self.__cause__


def format_activation_error(error: Any, stacks: bool = True) -> str:
    details = []
    seen = set()
    def visit(value: Any) -> None:
        if not isinstance(value, BaseException):
            details.append(safe_string(value))
            return
        if id(value) in seen:
            return
        seen.add(id(value))
        text = getattr(value, 'stack', None) if stacks else None
        if text is None:
            text = safe_string(value) if stacks else '%s: %s' % (
                getattr(value, 'name', 'Error' if isinstance(value, RuntimeError) else type(value).__name__), safe_string(value))
        details.append(text)
        cause = getattr(value, 'cause', getattr(value, '__cause__', None))
        if cause is not None:
            visit(cause)
        for member in getattr(value, 'errors', ()):
            visit(member)
    visit(error)
    return '\n'.join(details)


async def inactive_entries(ctx: Any, import_now: bool = True) -> List[Dict[str, Any]]:
    failures = []
    rejection_reasons = []
    for entry in ctx.get('loader').entries():
        try:
            if entry.disabled:
                continue
        except Exception as error:
            failures.append(dict(entry=entry, outcome=dict(kind='failed', error=error, phase='disabled expression failed')))
            continue
        fiber = entry.fiber
        if fiber is None or fiber.state == FiberState.DISPOSED:
            error = None
            if import_now:
                try:
                    await await_callback_result(entry.parent.tree.import_plugin(entry.options['name']))
                except Exception as failure:
                    error = failure
            outcome = dict(kind='failed', error=('failed to import' if fiber is None else 'fiber state %s' % fiber.state))
            if error is not None:
                outcome.update(error=error, phase='failed to import')
            failures.append(dict(entry=entry, outcome=outcome))
        elif fiber.state == FiberState.ACTIVE:
            continue
        elif fiber.state == FiberState.FAILED:
            try:
                await fiber.await_()
            except Exception as error:
                rejection_reasons.append(error)
                failures.append(dict(entry=entry, outcome=dict(kind='failed', error=error)))
        elif fiber.state == FiberState.PENDING:
            missing = [name for name in fiber.inject if fiber.ctx.get(name) is None]
            failures.append(dict(entry=entry, outcome=dict(kind='pending', missing=missing)))
        else:
            failures.append(dict(entry=entry, outcome=dict(kind='failed', error='fiber state %s' % fiber.state)))
    if rejection_reasons:
        from dsh.boot.app_boot import retain_assembled_rejection, release_assembled_rejection
        for reason in rejection_reasons:
            retain_assembled_rejection(reason)
        try:
            await asyncio.sleep(0)
        finally:
            for reason in rejection_reasons:
                release_assembled_rejection(reason)
    return failures


def failure_detail(outcome: Dict[str, Any], stacks: bool = True) -> str:
    phase = outcome.get('phase')
    return (phase + ': ' if phase is not None else '') + format_activation_error(outcome['error'], stacks)


def inactive_diagnostic(failure: Dict[str, Any], stacks: bool = True) -> str:
    entry, outcome = failure['entry'], failure['outcome']
    if outcome['kind'] == 'failed':
        detail = failure_detail(outcome, stacks)
    else:
        missing = outcome['missing']
        detail = 'pending (waiting for %s: %s)' % ('service' if len(missing) == 1 else 'services', ', '.join(missing) or 'unknown')
    return '%s (%s): %s' % (entry.options['id'], entry.options.get('name'), detail)


def activation_diagnostic(bin_name: str, failures: List[Dict[str, Any]], stacks: bool = True) -> str:
    return '%s: warning: %s %s did not activate\n%s\n' % (bin_name, len(failures),
        'entry' if len(failures) == 1 else 'entries', '\n'.join(inactive_diagnostic(row, stacks) for row in failures))


def startup_diagnostic(bin_name: str, failures: List[Dict[str, Any]], required: Any) -> str:
    lines = ['%s: startup failed: %s required %s did not activate' % (
        bin_name, len(required), 'plugin' if len(required) == 1 else 'plugins')]
    failed = [row for row in failures if row['outcome']['kind'] == 'failed']
    pending = sorted((row for row in failures if row['outcome']['kind'] == 'pending'),
        key=lambda row: row['entry'] not in required)
    def label(entry: Any) -> str:
        return entry.options['id'] + (' (required)' if entry in required else '')
    if failed:
        lines.extend(['', 'Failed plugins (%s):' % len(failed)])
        for row in failed:
            lines.extend(['  ' + label(row['entry']), '    Package: ' + row['entry'].options.get('name', '')])
            lines.extend('    ' + line for line in failure_detail(row['outcome']).split('\n'))
    if pending:
        width = max([len('Plugin')] + [len(label(row['entry'])) for row in pending]) + 2
        lines.extend(['', 'Plugins waiting for services (%s):' % len(pending), '  ' + 'Plugin'.ljust(width) + 'Missing services'])
        lines.extend('  ' + label(row['entry']).ljust(width) + (', '.join(row['outcome']['missing']) or 'unknown') for row in pending)
    return '\n'.join(lines)


async def audit_startup_entries(ctx: Any, bin_name: str, warn: Any = None) -> None:
    from dsh.boot.app_boot import _bootstrap_includes
    failures = await inactive_entries(ctx)
    required = {row['entry'] for row in failures if row['entry'] is _bootstrap_includes.get(ctx)
        or row['entry'].options['id'] in REQUIRED_STARTUP_ENTRY_IDS}
    if required:
        entries = [dict(id=row['entry'].options['id'], module=row['entry'].options.get('name'),
            required=row['entry'] in required, fiberState=row['entry'].fiber.state if row['entry'].fiber is not None else None,
            outcome=row['outcome']) for row in failures]
        raise StartupError(startup_diagnostic(bin_name, failures, required), entries)
    if failures:
        (warn if warn is not None else sys.stderr.write)(activation_diagnostic(bin_name, failures))


def capture_startup_composition(ctx: Any) -> Dict[str, Any]:
    rows = []
    for entry in ctx.get('loader').entries():
        fiber = entry.fiber
        try:
            state = 'disabled' if entry.disabled else 'failed' if fiber is None else STATE_NAMES[fiber.state]
        except Exception:
            state = 'failed'
        source = entry.parent.tree.ctx.baseUrl
        version = 'unknown'
        try:
            packages = ctx.get('pluginPackages')
            if source is not None and packages is not None:
                package = packages.packageOf(entry.options.get('name'), source)
                version = package.get('version', 'unknown') if isinstance(package, dict) else getattr(package, 'version', 'unknown')
        except Exception:
            pass
        missing = [name for name in fiber.inject if fiber.ctx.get(name) is None] if state == 'pending' and fiber is not None else []
        rows.append((entry, dict(id=entry.id, module=entry.options.get('name'), version=version, state=state,
            source=source if source is not None else 'unknown', missing=missing)))
    rows.sort(key=lambda row: row[1]['state'] == 'active')
    services = []
    omitted = 0
    for entry, state in rows:
        for service in state['missing']:
            if len(services) == 256:
                omitted += 1
                continue
            scope = get_isolate_symbol(entry.fiber.ctx, service)
            providers = []
            for key, impl in ctx.reflect.store.items():
                if impl.name != service:
                    continue
                owner = getattr(impl.ctx.fiber, 'entry', None)
                providers.append(dict(entry=owner.id if owner is not None else 'unknown', state=STATE_NAMES[impl.ctx.fiber.state],
                    visibility='same-scope' if key == scope else 'other-scope'))
            services.append(dict(consumer=state['id'], service=service, providers=providers))
    return dict(plugins=[state for entry, state in rows[:256]], services=services,
        omittedPlugins=max(0, len(rows) - 256), omittedServices=omitted)


auditStartupEntries = audit_startup_entries
captureStartupComposition = capture_startup_composition
