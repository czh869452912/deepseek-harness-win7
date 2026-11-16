"""Messages upload index with atomic generation-set invalidation."""
import json
import hashlib
import re

from dsh.cordis.file_lock import with_file_lock
from dsh.llm.deepseek_files_current import safeInteger
from dsh.llm.deepseek_upload_index import DeepSeekUploadIndex as _HistoricalIndex, reusable
from dsh.llm.pi_json import loads
from dsh.util.atomic_write import write_file_atomic


class InvalidUploadIndexError(ValueError):
    pass


def deepSeekFileScope(baseURL, credentials):
    value = baseURL.rstrip('/')+'\0'+credentials
    encoded = value.encode('utf-16-le', errors='surrogatepass').decode('utf-16-le', errors='replace').encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def parseRecord(value):
    if not isinstance(value, dict):
        raise InvalidUploadIndexError('llm-deepseek: upload index contains a non-object record')
    if (not isinstance(value.get('scope'), str) or not re.fullmatch('[0-9a-f]{64}', value['scope'])
            or any(not isinstance(value.get(key), str) or not re.fullmatch('sha256:[0-9a-f]{64}', value[key]) for key in ('attachmentId', 'variantId'))
            or not isinstance(value.get('fileId'), str) or not value['fileId']
            or any(not safeInteger(value.get(key)) for key in ('bytes', 'createdAt', 'expiresAt'))):
        raise InvalidUploadIndexError('llm-deepseek: upload index contains an invalid record')
    return {key: value[key] for key in ('scope', 'attachmentId', 'variantId', 'fileId', 'bytes', 'createdAt', 'expiresAt')}


def parseIndex(text):
    try: value = loads(text)
    except ValueError as error:
        raise InvalidUploadIndexError('llm-deepseek: upload index is not valid JSON') from error
    if not isinstance(value, dict):
        raise InvalidUploadIndexError('llm-deepseek: upload index is not an object')
    if value.get('formatVersion') != 3 or not isinstance(value.get('records'), list):
        raise InvalidUploadIndexError('llm-deepseek: unsupported upload index format')
    records = [parseRecord(row) for row in value['records']]
    keys = {(row['scope'], row['variantId']) for row in records}
    if len(keys) != len(records):
        raise InvalidUploadIndexError('llm-deepseek: upload index contains duplicate mappings')
    return records


class DeepSeekUploadIndex(_HistoricalIndex):
    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8', errors='replace') as stream:
                return parseIndex(stream.read())
        except (FileNotFoundError, InvalidUploadIndexError): return []

    async def _save(self, records):
        from dsh.cordis.json_text import stringify_json
        # Normalize integral Number spellings and well-formed JSON surrogates.
        value = json.loads(stringify_json(dict(formatVersion=3, records=records)))
        text = json.dumps(value, indent=2, ensure_ascii=False)+'\n'
        text = text.encode('utf-8', errors='backslashreplace').decode('utf-8')
        await write_file_atomic(self.path, text, mode=0o600, dir_mode=0o700)

    async def commit(self, candidate, now, refreshMarginMs):
        async def update():
            records = self._load()
            existing = next((row for row in records if row['scope'] == candidate['scope']
                and row['variantId'] == candidate['variantId'] and reusable(row, now, refreshMarginMs)), None)
            if existing is not None: return dict(record=existing, accepted=False)
            records = [row for row in records if reusable(row, now, refreshMarginMs)
                       and (row['scope'], row['variantId']) != (candidate['scope'], candidate['variantId'])]
            await self._save(records+[candidate])
            return dict(record=candidate, accepted=True)
        return await with_file_lock(self.path, update)

    async def remove(self, scope, generations):
        invalidated = {(row['variantId'], row['fileId']) for row in generations}
        async def update():
            records = self._load()
            keep = [row for row in records if not (row['scope'] == scope and (row['variantId'], row['fileId']) in invalidated)]
            if len(records) != len(keep): await self._save(keep)
        await with_file_lock(self.path, update)

    async def clear(self, scope):
        async def update():
            records = self._load()
            keep = [row for row in records if row['scope'] != scope]
            if len(records) != len(keep): await self._save(keep)
        await with_file_lock(self.path, update)
