"""Collect child prerequisites without recursively preparing current generations."""
import asyncio
import os
from types import SimpleNamespace

from dsh.core.session.json import UNDEFINED
from dsh.cordis.utils import _js_strict_equal
from dsh.session.file_revision import filesystem_identity
from dsh.session.format import SessionFormatUnsupportedMigrationError
from dsh.session.format_catalog import historicalSessionFormatCatalog, sessionFormatCatalog
from dsh.session.format_v3_to_v4 import historicalChildCatalogSource
from dsh.session.generation import JsonlGenerationSourceChangedError, identity, readDecodedJsonlSource
from dsh.session.jsonl_current import parseGenerationLogFilename
from dsh.session.preparations import throw_aborted


async def _stat(path):
    return await asyncio.get_running_loop().run_in_executor(None, lambda: filesystem_identity(path))


async def prepareCatalogFacts(parentId, sources, compression, signal, current_catalog=None):
    """Retain compact facts, local failures and physical revision witnesses."""
    facts, failures, witnesses = [], [], []
    for source in sources:
        throw_aborted(signal)
        path, source_header = source['path'], source['header']
        version = parseGenerationLogFilename(os.path.basename(path), compression)
        if version is UNDEFINED or version is None:
            raise SessionFormatUnsupportedMigrationError('unrecognized historical child generation ' + path)
        witness = dict(path=path, identity=await _stat(path))
        witnesses.append(witness)
        unavailable = dict(childId=source_header['id'], childCreatedAt=source_header['createdAt'],
                           descriptorCount=0, descriptor=None, sourcePath=path)
        try:
            catalog = historicalSessionFormatCatalog if version <= 3 else (current_catalog or sessionFormatCatalog)
            restored = await readDecodedJsonlSource(path, version, compression, dict(createRestore=lambda header:
                catalog.createRestore(header, dict(recovery='recoverable', validation='current'))), signal)
        except Exception as error:
            throw_aborted(signal)
            failures.append(dict(path=path, error=error))
            facts.append(unavailable)
            continue
        witness['identity'] = restored['identity']
        header = restored['artifact']['header']
        if (not _js_strict_equal(header.get('id', UNDEFINED), source_header['id'])
                or not _js_strict_equal(header.get('createdAt', UNDEFINED), source_header['createdAt'])
                or header.get('parentSession') != parentId or header.get('origin') != 'subagent'
                or any(not _js_strict_equal(header.get(key, UNDEFINED), source_header.get(key, UNDEFINED))
                       for key in ('cwd', 'isSeeded', 'delegationDepth', 'agentPreset'))):
            raise JsonlGenerationSourceChangedError(path)
        try:
            fact = historicalChildCatalogSource(restored['artifact'])
        except Exception as error:
            failures.append(dict(path=path, error=error))
            facts.append(unavailable)
            continue
        facts.append(dict(fact, sourcePath=path))

    async def validate():
        for witness in witnesses:
            if identity(await _stat(witness['path'])) != identity(witness['identity']):
                raise JsonlGenerationSourceChangedError(witness['path'])

    return SimpleNamespace(facts=facts, failures=failures, validate=validate)
