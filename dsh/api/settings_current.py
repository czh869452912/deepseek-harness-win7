"""Current Config-backed settings Remote; historical providers stay separate."""
import copy

from dsh.api.settings import CredentialsController, failure, settled
from dsh.core.session.json import UNDEFINED
from dsh.host.native_command import open_text_file
from dsh.typert.remote import Remote, TypertRemoteService


def namespace_view(descriptor):
    result = {key: copy.deepcopy(descriptor[key]) for key in
        ('autoGenerate', 'schema', 'value', 'base', 'user', 'applies', 'revision') if key in descriptor}
    result['ns'] = str(descriptor['ns'])
    result['secrets'] = [dict(path=list(secret['path']), set=secret['set']) for secret in descriptor.get('secrets', [])]
    return result


class CurrentSettingsController(TypertRemoteService):
    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'settingsController', {'namespace': 'settings'})
        self.open_text_file = (config or {}).get('openTextFile', open_text_file)
        ctx.plugin(CredentialsController)

    def _provider(self):
        value = self.ctx.get('settings')
        if value is None:
            raise failure('gateway/internal', 'settings service is absent: mount @deepseek-ai/dsh-settings with @deepseek-ai/dsh-config-editor in the profile composition')
        return value

    @Remote
    def describe(self):
        settings = self._provider()
        return dict(writable=settings.writable, hasDocument=True,
            namespaces=[namespace_view(row) for row in settings.describe(dict(redactSecrets=True))])

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
            if isinstance(ns, str):
                issue = dict(origin='string', code='too_small', minimum=1, inclusive=True, path=['ns'], message='Too small: expected string to have >=1 characters')
            else:
                received = 'undefined' if ns is UNDEFINED else 'null' if ns is None else 'array' if isinstance(ns, list) else 'boolean' if isinstance(ns, bool) else 'number' if isinstance(ns, (int, float)) else 'object'
                issue = dict(expected='string', code='invalid_type', path=['ns'], message='Invalid input: expected string, received '+received)
            raise failure('gateway/bad-request', 'invalid payload for settings.'+mode, dict(issues=[issue]))
        settings = self._provider()
        try:
            await settled(getattr(settings, mode)(ns, value, None if expected is UNDEFINED else expected))
        except Exception as error:
            expected = getattr(error, 'expected', None); actual = getattr(error, 'actual', None)
            message = getattr(error, 'message', str(error))
            if getattr(error, 'code', None) == 'SETTINGS_CONFLICT' and isinstance(message, str) and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in (expected, actual)):
                raise failure('settings/conflict', message, dict(ns=ns, expected=expected, actual=actual)) from error
            raise failure('settings/rejected', str(error), dict(ns=ns)) from error
        for row in settings.describe(dict(redactSecrets=True)):
            if row['ns'] == ns:
                return namespace_view(row)
        raise failure('gateway/internal', 'settings namespace "%s" was disposed after the %s' % (ns, mode))

    @Remote
    async def openSettingsDocument(self, signal):
        settings = self._provider()
        if signal.aborted:
            raise failure('gateway/cancelled', 'settings document open was aborted')
        try:
            path = await settled(settings.prepareDocument())
        except Exception as error:
            raise failure('gateway/cancelled' if signal.aborted else 'gateway/internal',
                'settings document preparation was aborted' if signal.aborted else 'settings document preparation failed: '+str(error)) from error
        if signal.aborted:
            raise failure('gateway/cancelled', 'settings document open was aborted')
        try:
            await self.open_text_file(path, signal)
            return dict(opened=True)
        except Exception as error:
            raise failure('gateway/cancelled' if signal.aborted else 'gateway/internal',
                'settings document open was aborted' if signal.aborted else 'path open failed: '+str(error)) from error
