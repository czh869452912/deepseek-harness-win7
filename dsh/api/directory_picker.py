"""Directory picker capability and cancellation boundary for generated Remotes."""
from dsh.api.settings import failure
from dsh.host.directory_picker.base import DirectoryPickerError
from dsh.typert.remote import Remote, TypertRemoteService
from dsh.typert.artifact import UNDEFINED


class DirectoryPickerController(TypertRemoteService):
    inject = ['directoryPicker']

    def __init__(self, ctx):
        super().__init__(ctx, 'directoryPickerController', {'namespace': 'directoryPicker'})

    def _capability(self, kind, method):
        cap = self.ctx.get('directoryPicker').capability()
        if cap['kind'] != kind:
            raise failure('directory-picker-unavailable',
                          'directoryPicker.%s needs the %s capability; the composed picker serves "%s"' % (method, kind, cap['kind']),
                          {'capability': cap['kind']})
        return cap[method]

    @Remote
    async def pick(self, signal):
        pick = self._capability('native', 'pick')
        try:
            return await pick(signal)
        except Exception as error:
            raise failure('cancelled' if signal.aborted else 'internal',
                          'directory picker was aborted' if signal.aborted else 'directory picker failed: ' + str(error)) from error

    @Remote
    async def list(self, path, signal):
        listing = self._capability('browse', 'list')
        try:
            return await listing(None if path is UNDEFINED else path, signal)
        except Exception as error:
            if signal.aborted:
                raise failure('cancelled', 'directory listing was aborted') from error
            raise self._browse_failure(error) from error

    @Remote
    async def createDirectory(self, path, name):
        if not isinstance(name, str) or not name.strip() or name in ('.', '..') or '/' in name or '\\' in name:
            raise failure('bad-request', 'invalid payload for host.createDirectory',
                          {'issues': [{'code': 'custom', 'path': [], 'message': 'host.createDirectory requires a single non-blank path segment name'}]})
        create = self._capability('browse', 'createDirectory')
        try:
            return await create(path, name)
        except Exception as error:
            raise self._browse_failure(error) from error

    @staticmethod
    def _browse_failure(error):
        if isinstance(error, DirectoryPickerError):
            return failure(error.code, str(error), {'path': error.path})
        return failure('internal', str(error))
