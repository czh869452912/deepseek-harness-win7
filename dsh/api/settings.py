"""Redacted settings and one-way credential writes over Typert Remote."""
import asyncio
import copy
import inspect
import os

from dsh.credentials.credentials import credential_ref
from dsh.settings.provider import SettingsConflictError
from dsh.settings.types import settings_namespace
from dsh.presets.preset import UnknownPresetError, InvalidPresetIdError, PresetExistsError, PresetNotWritableError
from dsh.typert.remote import TypertRemoteService, TypertRemoteFailure, Remote
from dsh.typert.artifact import UNDEFINED
from dsh.host.native_command import can_open_path, open_path, open_text_file


async def settled(value):
    return await value if inspect.isawaitable(value) else value


def failure(code, message, details=None):
    return TypertRemoteFailure(dict(code=code, message=message, details=details or {}))


def provider(ctx, key, example):
    value = ctx.get(key)
    if value is None:
        raise failure('internal', '%s service is absent: this deployment does not mount a %s provider (e.g. %s) in its composition' %
                      (key, 'credential' if key == 'credentials' else key, example))
    return value


def namespace_view(value):
    result = {key: copy.deepcopy(value[key]) for key in ('ns', 'schema', 'value', 'applies', 'revision', 'base', 'user') if key in value}
    result['secrets'] = [dict(path=list(secret['path']), set=secret['set']) for secret in value.get('secrets', [])]
    return result


class CredentialsController(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, 'credentialsController', {'namespace': 'credentials'})

    def _provider(self):
        return provider(self.ctx, 'credentials', '@deepseek-ai/dsh-credentials-local')

    def _validate(self, method, refs, value=UNDEFINED):
        try:
            if not isinstance(refs, list) or len(refs) > 64:
                raise ValueError('refs must be an array of at most 64 references')
            for ref in refs:
                credential_ref(ref)
            if method == 'set' and (not isinstance(value, str) or not value):
                raise ValueError('value must be a non-empty string')
        except (ValueError, TypeError):
            # Never include credential input in diagnostics.
            raise failure('bad-request', 'invalid payload for credentials.' + method,
                          {'issues': [{'code': 'custom', 'path': ['value' if method == 'set' else 'refs'], 'message': 'Invalid input'}]})

    @Remote
    async def describe(self, refs):
        self._validate('describe', refs)
        credentials = self._provider()
        async def describe(ref):
            info = await settled(credentials.describe(ref))
            return ref, {key: info[key] for key in ('configured', 'source', 'writable') if key in info}
        return dict(await asyncio.gather(*(describe(ref) for ref in refs)))

    @Remote
    async def set(self, ref, value):
        self._validate('set', [ref], value)
        credentials = self._provider()
        try:
            await settled(credentials.set(ref, value))
        except Exception as error:
            raise failure('credential-rejected', str(error), {'ref': ref}) from error
        return UNDEFINED

    @Remote
    async def unset(self, ref):
        self._validate('unset', [ref])
        credentials = self._provider()
        try:
            await settled(credentials.unset(ref))
        except Exception as error:
            raise failure('credential-rejected', str(error), {'ref': ref}) from error
        return UNDEFINED


class SettingsController(TypertRemoteService):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'settingsController', {'namespace': 'settings'})
        self.native_open = (config or {}).get('nativeOpen')
        ctx.plugin(CredentialsController)

    def _provider(self):
        return provider(self.ctx, 'settings', '@deepseek-ai/dsh-settings-file')

    @Remote
    def describe(self):
        settings = self._provider()
        return dict(writable=settings.writable, hasDocument=settings.document_path is not None,
                    namespaces=[namespace_view(row) for row in settings.describe({'redactSecrets': True})])

    @Remote
    def canOpenAgentPresetDirectory(self):
        return self.native_open if self.native_open is not None else can_open_path()

    @Remote
    async def update(self, ns, patch, expectedRevision):
        return await self._write(ns, 'update', patch, expectedRevision)

    @Remote
    async def replace(self, ns, section, expectedRevision):
        return await self._write(ns, 'replace', section, expectedRevision)

    @Remote
    async def mutate(self, ns, ops, expectedRevision):
        return await self._write(ns, 'mutate', ops, expectedRevision)

    async def _write(self, ns, mode, value, expected):
        if not isinstance(ns, str) or not ns:
            raise failure('bad-request', 'invalid payload for settings.' + mode, {'issues': [{'path': ['ns'], 'message': 'Invalid input'}]})
        settings = self._provider()
        try:
            settings_namespace(ns)
            await settled(getattr(settings, mode)(ns, value, None if expected is UNDEFINED else expected))
        except SettingsConflictError as error:
            raise failure('settings-conflict', str(error), dict(ns=ns, expected=error.expected, actual=error.actual)) from error
        except Exception as error:
            raise failure('settings-rejected', str(error), {'ns': ns}) from error
        for row in settings.describe({'redactSecrets': True}):
            if row['ns'] == ns:
                return namespace_view(row)
        raise failure('internal', 'settings namespace "%s" was disposed after the %s' % (ns, mode))

    @Remote
    async def openSettingsDocument(self, signal):
        settings = self._provider()
        if signal.aborted:
            raise failure('cancelled', 'settings document open was aborted')
        try:
            path = await settled(settings.prepare_document())
        except Exception as error:
            raise failure('cancelled' if signal.aborted else 'internal',
                'settings document preparation was aborted' if signal.aborted else 'settings document preparation failed: ' + str(error)) from error
        if path is None:
            raise failure('internal', 'settings provider has no local document to open')
        if signal.aborted:
            raise failure('cancelled', 'settings document open was aborted')
        try:
            await open_text_file(path, signal)
            return {'opened': True}
        except Exception as error:
            raise failure('cancelled' if signal.aborted else 'internal',
                'settings document open was aborted' if signal.aborted else 'path open failed: ' + str(error)) from error

    @Remote
    async def openAgentPresetDirectory(self, agentPreset, signal):
        if not agentPreset:
            raise failure('bad-request', 'agent preset id must not be empty')
        presets = self.ctx.get('agentPresets')
        if presets is None:
            raise failure('agent-preset-not-found', 'this deployment composes no agent presets', dict(agentPreset=agentPreset, available=[]))
        try:
            preset = await presets.resolve(agentPreset)
            if preset.trust != 'user':
                raise PresetNotWritableError(preset.id, 'it ships with the deployment')
            directory = os.path.dirname(preset.path)
        except UnknownPresetError as error:
            raise failure('agent-preset-not-found', str(error), dict(agentPreset=error.preset_id, available=list(error.available))) from error
        except (PresetNotWritableError, InvalidPresetIdError, PresetExistsError) as error:
            raise failure('agent-preset-read-only' if isinstance(error, PresetNotWritableError) else 'agent-preset-invalid',
                          str(error), dict(agentPreset=agentPreset, reason=str(error))) from error
        except Exception as error:
            raise failure('internal', 'agent preset "%s": %s' % (agentPreset, error)) from error
        if not self.canOpenAgentPresetDirectory():
            return dict(opened=False, path=directory)
        try:
            await open_path(directory, signal)
            return {'opened': True}
        except Exception as error:
            raise failure('cancelled' if signal.aborted else 'internal',
                'path open was aborted' if signal.aborted else 'path open failed: ' + str(error)) from error
