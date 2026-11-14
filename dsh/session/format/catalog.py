"""Build-static dispatch over released codecs and adjacent streaming migrations."""
from dsh.core.session.json import UNDEFINED, FrozenDict
from dsh.cordis.utils import js_to_string, _js_strict_equal
from .chain import call, member, createSessionFormatChain, SessionFormatEventCollector
from .error import SessionFormatError, SessionFormatUnsupportedMigrationError
from .json import inspectSessionFormatVersion, snapshotSessionFormatHeader, sessionFormatVersion


class SessionFormatCatalog:
    def __init__(self, options):
        self._options = dict(options)
        self._chain = createSessionFormatChain(options)
        self.currentVersion = self._chain.currentVersion
        self._codecs = {}
        for codec in options['codecs']:
            version = sessionFormatVersion(member(codec, 'version'), 'Session format codec version')
            if version in self._codecs:
                raise SessionFormatError('Session format codec v%s is duplicated' % js_to_string(version))
            self._codecs[version] = FrozenDict({key: member(codec, key) for key in ('version', 'decodeHeader', 'createDecoder')})
        for version in range(int(self.currentVersion) + 1):
            if version not in self._codecs:
                raise SessionFormatError('Session format codec v%s is missing' % version)
        if len(self._codecs) != self.currentVersion + 1:
            invalid = next(version for version in self._codecs if version > self.currentVersion)
            raise SessionFormatError('Session format codec v%s is newer than current v%s' % (
                js_to_string(invalid), js_to_string(self.currentVersion)))

    def readHeader(self, value):
        try:
            stored = inspectSessionFormatVersion(value)
        except Exception as error:
            return self._malformed(error)
        if stored > self.currentVersion:
            return self._unsupported(stored, self._newer(stored))
        try:
            decoded = snapshotSessionFormatHeader(call(self._codecs[stored], 'decodeHeader', value),
                'format v%s header' % js_to_string(stored))
            header = self._chain.migrateHeader(decoded)
            return FrozenDict(status='current' if stored == self.currentVersion else 'migration-required',
                storedVersion=stored, targetVersion=self.currentVersion, header=header)
        except SessionFormatUnsupportedMigrationError as error:
            return self._unsupported(stored, str(error))
        except Exception as error:
            return self._malformed(error, stored)

    def _newer(self, version):
        return 'stored Session uses newer format v%s; this build writes v%s' % (
            js_to_string(version), js_to_string(self.currentVersion))

    def _unsupported(self, stored, reason):
        return FrozenDict(status='unsupported', storedVersion=stored, targetVersion=self.currentVersion, reason=reason)

    def _malformed(self, error, stored=UNDEFINED):
        result = dict(status='malformed')
        if stored is not UNDEFINED:
            result['storedVersion'] = stored
        result.update(targetVersion=self.currentVersion, reason=str(error))
        return FrozenDict(result)

    def encodeCurrentHeader(self, header, inheritedEventCount):
        if inspectSessionFormatVersion(header) != self.currentVersion:
            raise SessionFormatError('encodeCurrent requires Session format v%s' % js_to_string(self.currentVersion))
        encoded = call(self._options['currentEncoder'], 'encodeHeader', header, inheritedEventCount)
        if inspectSessionFormatVersion(encoded) != self.currentVersion:
            raise SessionFormatError('current Session codec returned a non-current header')
        return encoded

    def encodeCurrentEvent(self, event):
        return call(self._options['currentEncoder'], 'encodeEvent', event)

    def createRestore(self, value, options):
        version = inspectSessionFormatVersion(value)
        if version > self.currentVersion:
            raise SessionFormatUnsupportedMigrationError(self._newer(version))
        decoder = call(self._codecs[version], 'createDecoder', value, options['recovery'])
        cut = member(decoder, 'headerInheritedEventCount')
        if version == self.currentVersion:
            restorer = self._options['restoreCurrent'] if options['validation'] == 'current' else lambda artifact: artifact
            return CurrentSessionFormatRestore(decoder, cut, restorer, self.currentVersion)
        collector = SessionFormatEventCollector()
        migration = self._chain.createStream(member(decoder, 'header'), cut, collector)
        restorer = self._options['restoreCurrent'] if options['validation'] == 'current' else self._options['restoreTransformedCurrent']
        return MigratingSessionFormatRestore(decoder, cut, migration, collector, restorer,
            options['validation'], version, self.currentVersion)


def finishDecoder(decoder, context, sourceCut):
    cut = call(decoder, 'finish', context)
    if sourceCut is not UNDEFINED and not _js_strict_equal(cut, sourceCut):
        raise SessionFormatError('streaming decoder changed its predeclared inherited cut')
    return cut


def restoreCurrentVersion(artifact, currentVersion):
    version = member(artifact['header'], 'version')
    if not _js_strict_equal(version, currentVersion):
        raise SessionFormatError('current Session restorer returned v%s; expected v%s' % (
            js_to_string(version), js_to_string(currentVersion)))
    return artifact


class CurrentSessionFormatRestore:
    def __init__(self, decoder, sourceCut, restoreArtifact, currentVersion):
        self._decoder, self._sourceCut, self._restore = decoder, sourceCut, restoreArtifact
        self._currentVersion = currentVersion
        self.header = member(decoder, 'header')
        self._collector = SessionFormatEventCollector()

    def decodeRow(self, row):
        call(self._decoder, 'decodeRow', row, self._collector)

    def finish(self):
        cut = finishDecoder(self._decoder, self._collector, self._sourceCut)
        return restoreCurrentVersion(self._restore(dict(header=self.header, inheritedEventCount=cut,
            events=self._collector.values)), self._currentVersion)


class MigratingSessionFormatRestore:
    def __init__(self, decoder, sourceCut, migration, collector, restoreArtifact, validation, sourceVersion, currentVersion):
        self._decoder, self._sourceCut = decoder, sourceCut
        self._migration, self._collector, self._restore = migration, collector, restoreArtifact
        self._validation, self._sourceVersion, self._currentVersion = validation, sourceVersion, currentVersion
        self.header = migration.header

    def decodeRow(self, row):
        call(self._decoder, 'decodeRow', row, self)

    def emitEvent(self, event):
        self._migration.emitEvent(event)

    def emitRun(self, run):
        self._migration.emitRun(run)

    def finish(self):
        finishDecoder(self._decoder, self, self._sourceCut)
        artifact = dict(header=self.header, inheritedEventCount=self._migration.finish(), events=self._collector.values)
        try:
            restored = self._restore(artifact)
        except Exception as error:
            if self._validation == 'current' or isinstance(error, SessionFormatUnsupportedMigrationError):
                raise
            wrapped = SessionFormatUnsupportedMigrationError('Session migration from v%s to v%s refuses the transformed artifact: %s' % (
                js_to_string(self._sourceVersion), js_to_string(self._currentVersion), str(error)))
            wrapped.cause = error
            raise wrapped from error
        return restoreCurrentVersion(restored, self._currentVersion)


def createSessionFormatCatalog(options):
    return SessionFormatCatalog(options)
