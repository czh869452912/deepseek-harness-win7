"""Owned host orchestration for the pinned SDK's browser WASM workers."""
import asyncio
from collections import OrderedDict
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from .browser_carrier import BrowserCarrier
from .contracts import resolve_request
from .errors import OfficeKitError
from .file_transaction import FileExport, ImageExport, disk_call, read_document
from .font_discovery import host_font_volume
from .outputs import _remove_tree
from .metadata_cache import read_cache, publish_cache

RESOURCES = Path(__file__).with_name('browser_runtime')
MANIFEST_SHA256 = '6f26d2a7f785c30fd99bc2c4965b51ee1aac898f752e430c2bcc86c5ba922db1'
ENGINE_FILES = dict(loader='dsoffice.cjs', wasm='dsoffice.wasm', data='dsoffice.data', metadata='dsoffice.data.js.metadata')
CODES = frozenset(('input-too-large', 'output-too-large', 'invalid-document', 'unsupported-format', 'invalid-output', 'timeout', 'unavailable', 'failed'))
ENGINE_SHA256 = {
    'dsoffice.cjs': 'c9248ef54385015475b15ae2baca41d9f7a8bd0b8538904da6a1fcd16c5305a1',
    'dsoffice.wasm': 'bb7d1121c7200020f0b6219e37655719cde0c63f905f9826c43c40bf5a7c17c8',
    'dsoffice.data': '0bea03629341de18dc90bdfc1e67a2f3b791e31ef9fe22888c288226e8bd5b15',
    'dsoffice.data.js.metadata': 'ffab1d431c3ecdac3f2438f5e229b2e9a83364fed02b1732e5c327ab43d6b04d',
}


def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def _check_result(result):
    if not result.get('ok'):
        raise OfficeKitError(result.get('code') if result.get('code') in CODES else 'failed', result.get('error', 'LibreOffice conversion failed.'))
    if result.get('adapter') != dict(openDescriptors=0, retainedReadBuffers=0):
        raise OfficeKitError('failed', 'LibreOffice worker retained a font resource.')
    return result


async def _drain(task):
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
        except BaseException:
            break
    if not task.cancelled():
        task.exception()


def _resources(package):
    raw = (RESOURCES / 'manifest.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise OfficeKitError('unavailable', 'Office browser manifest differs.')
    manifest = json.loads(raw)
    for name, expected in manifest['resources'].items():
        if Path(name).name != name or ':' in name or hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest() != expected:
            raise OfficeKitError('unavailable', 'Office browser resource differs.')
    root = Path(package)
    pkg = json.loads((root / 'package.json').read_text(encoding='utf-8'))
    prebuilds = json.loads((root / 'prebuilds.json').read_text(encoding='utf-8'))
    if pkg.get('name') != '@deepseek-ai/libreoffice-kit-wasm' or pkg.get('version') != '0.2.3' or prebuilds.get('version') != '0.2.3' or prebuilds.get('status') != 'built' or prebuilds.get('platform') != 'wasm' or prebuilds.get('schemaVersion') != 1:
        raise OfficeKitError('unavailable', 'Installed LibreOfficeKit WASM package is incompatible or incomplete.')
    if prebuilds.get('engine') != dict(kind='wasm', programDirectory='/instdir/program', **{key: 'assets/' + value for key, value in ENGINE_FILES.items()}):
        raise OfficeKitError('unavailable', 'Installed LibreOfficeKit WASM engine layout differs.')
    assets = {'sdk.js': RESOURCES / 'worker.js'}
    for name in ENGINE_FILES.values():
        path = root / 'assets' / name
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for data in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(data)
        if digest.hexdigest() != ENGINE_SHA256[name] or digest.hexdigest() != prebuilds['files'].get('assets/' + name):
            raise OfficeKitError('unavailable', 'Installed LibreOfficeKit WASM asset differs.')
        assets[name] = path
    return assets


class _State:
    def __init__(self, engine, options):
        self.engine, self.options = engine, options
        self.previous, self.generation, self.cache = [], None, OrderedDict()
        self.scan = None

    async def acquire(self, signal):
        signal.throwIfAborted()
        while self.scan is not None and self.scan['controller'].signal.aborted:
            await _drain(self.scan['task'])
            signal.throwIfAborted()
        if self.scan is None:
            controller = AbortController()
            record = dict(controller=controller, waiters=0)
            async def scan():
                try:
                    def discover():
                        values = dict(self.options)
                        if values['includeOfficeFonts']:
                            values.pop('fontDirectories')
                        return host_font_volume(values, controller.signal.throwIfAborted)
                    volume, host = await disk_call(discover)
                    cached = await disk_call(read_cache, self.options['fontMetadataCacheDirectory'],
                                             self.options['maxFontMetadataCacheBytes'], controller.signal)
                    options = dict(self.options, fontDirectories=volume.paths, fontMetadataCacheDirectory=False)
                    result = _check_result(await self.engine._worker(dict(options=options, host=host, volume=volume.manifest(),
                        previous=self.previous, scanOnly=True, metadataCache=self.options['fontMetadataCacheDirectory'] is not False,
                        _metadataBytes=cached), volume.assets, controller.signal))
                    snapshot = result['snapshot']
                    await disk_call(publish_cache, self.options['fontMetadataCacheDirectory'], result.get('metadataCache'),
                                    self.options['maxFontMetadataCacheBytes'], controller.signal)
                    self.previous = snapshot['records'] if len(_json(snapshot['records']).encode('utf-8')) <= self.options['maxFontMetadataCacheBytes'] else []
                    return volume, host, snapshot
                finally:
                    if self.scan is record:
                        self.scan = None
            record['task'] = asyncio.create_task(scan())
            record['task'].add_done_callback(lambda done: None if done.cancelled() else done.exception())
            self.scan = record
        record = self.scan
        record['waiters'] += 1
        stopped = asyncio.create_task(signal.wait_aborted())
        try:
            await asyncio.wait((record['task'], stopped), return_when=asyncio.FIRST_COMPLETED)
            signal.throwIfAborted()
            volume, host, snapshot = record['task'].result()
            if self.generation != snapshot['generation']:
                self.generation = snapshot['generation']
                self.cache.clear()
            return volume, host, snapshot
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)
            record['waiters'] -= 1
            if not record['waiters'] and self.scan is record:
                record['controller'].abort(RuntimeError('All font scan waiters stopped.'))
                await _drain(record['task'])

    def merge(self, generation, messages):
        if self.generation != generation:
            return
        for message in messages:
            for entry in message['entries']:
                prior = self.cache.pop(entry['key'], {})
                faces = OrderedDict(((face['path'], face['faceIndex']), face) for face in prior.get('faces', []))
                faces.update(((face['path'], face['faceIndex']), face) for face in entry['faces'])
                merged = dict(entry, codePoints=sorted(set(prior.get('codePoints', []) + entry['codePoints'])),
                              emptyRequest=prior.get('emptyRequest') is True or entry['emptyRequest'], faces=list(faces.values()))
                if 'missingFamily' in prior:
                    merged['missingFamily'] = prior['missingFamily']
                self.cache[entry['key']] = merged
        while len(self.cache) > self.options['maxFontResolutionEntries']:
            self.cache.popitem(last=False)


class BrowserOfficeEngine:
    """One service owner; converters reuse bounded state by resolved options."""
    def __init__(self, executable, package, *, temporary_directory=None):
        self.carrier = BrowserCarrier(executable, temporary_directory=temporary_directory)
        self.package, self.temporary_directory = str(package), temporary_directory
        self.assets = None
        self.states, self.converters = OrderedDict(), set()
        self.closing = None
        self.initialization = None
        self.creations = set()

    async def createConverter(self, options=None):
        task = asyncio.create_task(self._create(options))
        self.creations.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await _drain(task)
            if not task.cancelled() and task.exception() is None:
                await task.result().dispose()
            raise
        finally:
            self.creations.discard(task)

    async def _create(self, options):
        if self.closing is not None:
            raise OfficeKitError('unavailable', 'The Office engine is closed.')
        resolved = await disk_call(resolve_request, 'options', {} if options is None else options)
        if self.initialization is None:
            self.initialization = CleanupPromise(disk_call(_resources, self.package))
        try:
            self.assets = await self.initialization
        except BaseException as cause:
            if isinstance(cause, asyncio.CancelledError):
                raise
            self.initialization = None
            if isinstance(cause, OfficeKitError):
                raise
            raise OfficeKitError('unavailable', str(cause), cause=cause) from None
        if self.closing is not None:
            raise OfficeKitError('unavailable', 'The Office engine is closed.')
        key = _json({name: value for name, value in resolved.items() if name not in ('timeoutMs', 'maxInputBytes', 'maxOutputBytes', 'maxImageResolution', 'maxArchiveEntries', 'maxUncompressedBytes')})
        state = self.states.pop(key, None) or _State(self, resolved)
        self.states[key] = state
        while len(self.states) > 16:
            self.states.popitem(last=False)
        converter = BrowserConverter(self, resolved, state)
        self.converters.add(converter)
        return converter

    async def _worker(self, request, assets, signal):
        directory = tempfile.mkdtemp(prefix='dsh-office-request-', dir=self.temporary_directory)
        try:
            request = dict(request, engine=dict(backend='wasm', programDirectory='/instdir/program', **ENGINE_FILES))
            cached = request.pop('_metadataBytes', None)
            assets = dict(assets)
            if cached is not None:
                cache_path = Path(directory) / 'metadata-cache.json'
                await disk_call(cache_path.write_bytes, cached)
                assets['metadata-cache'] = cache_path
                request['volume']['files']['/metadata/font-metadata.json'] = dict(route='metadata-cache',
                    identity=dict(dev='0', ino='0', size=len(cached), mtimeNs='0', ctimeNs='0'))
            path = Path(directory) / 'request.json'
            await disk_call(path.write_text, _json(request), 'utf-8')
            selected = dict(self.assets, **assets, **{'request.json': path})
            return await self.carrier.run("importScripts('sdk.js')", selected, signal=signal,
                                          timeout=2147483, max_result_bytes=max(140000000, request['options']['maxOutputBytes'] * 3 + request['options']['maxFontMetadataCacheBytes'] * 3))
        finally:
            await disk_call(_remove_tree, directory)

    def close(self):
        if self.closing is None:
            async def close():
                await asyncio.gather(*tuple(self.creations), return_exceptions=True)
                states = set(self.states.values()) | {converter.state for converter in self.converters}
                await asyncio.gather(*(converter.dispose() for converter in tuple(self.converters)), return_exceptions=False)
                await self.carrier.close()
                if self.initialization is not None:
                    await asyncio.gather(self.initialization.task, return_exceptions=True)
                for state in states:
                    state.previous = []
                    state.cache.clear()
                self.states.clear()
            self.closing = CleanupPromise(close())
        return self.closing


class BrowserConverter:
    backend = 'wasm'

    def __init__(self, engine, options, state):
        self.engine, self.options, self.state = engine, options, state
        self.lifetime = AbortController()
        self.lock, self.active, self.disposal = asyncio.Lock(), set(), None

    async def render(self, request, signal=None):
        return await self._submit('render', request, signal)

    async def convert(self, request, signal=None):
        return await self._submit('convert', request, signal)

    async def recalculate(self, request, signal=None):
        return await self._submit('recalculate', request, signal)

    async def renderImages(self, request, signal=None):
        return await self._submit('images', request, signal)

    async def _submit(self, kind, request, signal):
        controller = AbortController()
        disposers = [self.lifetime.signal.add_listener('abort', lambda reason: controller.abort(reason))]
        if signal is not None:
            disposers.append(signal.add_listener('abort', lambda reason: controller.abort(reason)))
        async def run():
            # Public validation precedes file ownership and queue admission,
            # but its process/disk work still belongs to this converter.
            operation = await disk_call(resolve_request, kind, request)
            return await self._execute(operation, controller)
        task = asyncio.create_task(run())
        self.active.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            controller.abort(asyncio.CancelledError())
            await _drain(task)
            raise
        finally:
            self.active.discard(task)
            for dispose in disposers:
                dispose()

    async def _execute(self, operation, controller):
        signal = controller.signal
        # A queued request can abort without acquiring the slot or its timeout.
        waiter = asyncio.create_task(self.lock.acquire())
        stopped = asyncio.create_task(signal.wait_aborted())
        acquired = False
        try:
            await asyncio.wait((waiter, stopped), return_when=asyncio.FIRST_COMPLETED)
            if waiter.done() and not waiter.cancelled():
                acquired = waiter.result()
            signal.throwIfAborted()
        finally:
            if not waiter.done():
                waiter.cancel()
            stopped.cancel()
            await asyncio.gather(waiter, stopped, return_exceptions=True)
            if signal.aborted and acquired:
                self.lock.release()
        image = operation.get('kind') == 'images'
        timer = asyncio.get_running_loop().call_later(self.options['timeoutMs'] / 1000,
            lambda: controller.abort(OfficeKitError('timeout', 'LibreOffice image rendering timed out.' if image else 'LibreOffice conversion timed out.')))
        owned = ImageExport(operation['outputDir']) if image else FileExport(operation['outputPath'])
        failure = None
        directory = None
        try:
            signal.throwIfAborted()
            await disk_call(owned.open)
            data = await disk_call(read_document, operation['inputPath'], self.options['maxInputBytes'], signal)
            directory = tempfile.mkdtemp(prefix='dsh-office-input-', dir=self.engine.temporary_directory)
            path = Path(directory) / ('input.' + operation['extension'])
            await disk_call(path.write_bytes, data)
            volume, host, snapshot = await self.state.acquire(signal)
            virtual = dict(operation, inputPath='/input.' + operation['extension'])
            if image:
                virtual['outputDir'] = '/output'
            result = await self.engine._worker(dict(options=dict(self.options, fontDirectories=volume.paths, fontMetadataCacheDirectory=False),
                volume=volume.manifest(), host=host, readySnapshot=snapshot, generation=snapshot['generation'],
                fontCache=list(self.state.cache.values()), inputRoute=path.name, extension=operation['extension'], operation=virtual),
                dict(volume.assets, **{path.name: path}), signal)
            self.state.merge(snapshot['generation'], result.get('fontCache', []))
            _check_result(result)
            await disk_call(volume.validate, snapshot['records'])
            signal.throwIfAborted()
            if image:
                result = copy.deepcopy(result)
                manifest = result['images']
                manifest['inputPath'] = operation['inputPath']
                for item in manifest['images']:
                    virtual_path = item['path']
                    if not virtual_path.startswith('/output/') or '/' in virtual_path[len('/output/'):] or '\\' in virtual_path:
                        raise OfficeKitError('invalid-output', 'The converter reported an image outside its output directory.')
                    item['path'] = os.path.join(operation['outputDir'], virtual_path[len('/output/'):])
                    transaction = FileExport(item['path'])
                    try:
                        await disk_call(transaction.open)
                        await disk_call(transaction.write, result['files'][virtual_path], signal)
                    finally:
                        await disk_call(transaction.close)
                transaction = FileExport(os.path.join(operation['outputDir'], 'manifest.json'))
                try:
                    await disk_call(transaction.open)
                    await disk_call(transaction.write, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'), signal)
                finally:
                    await disk_call(transaction.close)
                signal.throwIfAborted()
                owned.succeeded = True
                return manifest
            await disk_call(owned.write, result['output'], signal, False)
            signal.throwIfAborted()
            owned.succeeded = True
            return result['metadata']
        except BaseException as cause:
            failure = cause
            signal.throwIfAborted()
            raise
        finally:
            timer.cancel()
            try:
                if directory is not None:
                    await disk_call(_remove_tree, directory)
            finally:
                try:
                    if image:
                        await disk_call(owned.close)
                    else:
                        await disk_call(owned.close, failure)
                finally:
                    self.lock.release()

    def dispose(self):
        if self.disposal is None:
            self.lifetime.abort(RuntimeError('LibreOffice converter is disposed.'))
            async def dispose():
                await asyncio.gather(*tuple(self.active), return_exceptions=True)
                self.engine.converters.discard(self)
            self.disposal = CleanupPromise(dispose())
        return self.disposal
