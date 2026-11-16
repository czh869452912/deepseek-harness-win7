"""Listed bundle detail documents and fresh images over shared file readers."""
from dsh.boot.plugin_bundle_metadata import bundle_directory
from dsh.boot.runtime_resolution import _field
from dsh.boot.semver import parse
from dsh.cordis.utils import js_to_string, _UNDEFINED
from dsh.typert.remote import RemoteError
from dsh.util.plugin_detail import (DetailFailure, LocalFiles, language_chain,
    npm_file_source_order, read_package_document, detail_image)
from dsh.util.plugin_detail_http import NpmFiles


def files_of(bundle, preferred, options):
    if bundle['availability'] != 'missing':
        try:
            profile = options['profile']
            directory = bundle_directory(bundle['name'], _field(profile, 'dir'), _field(profile, 'installAnchor'))
        except Exception as error:raise RemoteError('plugin-manager/unknown-bundle', str(error), dict(name=bundle['name']), error)
        return LocalFiles(directory, js_to_string(bundle.get('version', _UNDEFINED)))
    version = _field(bundle.get('installTarget'), 'version')
    try:
        parsed = parse(version)
        if parsed.canonical() != version or parsed.build is not None:return None
    except ValueError:return None
    sources = npm_file_source_order(options['npmFileSources'], preferred)
    return NpmFiles(bundle['name'], version, sources, dict(timeoutMs=options['timeoutMs'], lifetime=options['lifetime']))


def remote_failure(error):
    if isinstance(error, DetailFailure):
        raise RemoteError('plugin-manager/detail-unavailable', error.message, dict(reason=error.reason), error)
    raise error


async def read_bundle_document(bundle, language, preferred, options):
    try:languages = language_chain(language)
    except Exception as error:raise RemoteError('plugin-manager/invalid-language', str(error), dict(language=language), error)
    files = files_of(bundle, preferred, options)
    if files is None:return dict(status='none')
    try:document = await read_package_document(files, '', languages, options['maxDocumentBytes'], options['lifetime'])
    except Exception as error:remote_failure(error)
    return dict(status='none') if document is None else dict(status='found', **document)


async def read_bundle_image(bundle, document, destination, preferred, options):
    image = detail_image(document, destination)
    files = None if image is None else files_of(bundle, preferred, options)
    if image is None or files is None:return None
    try:data = await files.read(image['path'], options['maxImageBytes'], options['lifetime'])
    except Exception as error:remote_failure(error)
    return None if data is None else dict(bytes=data, mediaType=image['mediaType'])
