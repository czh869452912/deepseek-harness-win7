"""Request-owned Files deadlines, one stale-id retry and image diagnostics."""
from bisect import bisect_right
from functools import lru_cache
import json
from pathlib import Path
import re

from dsh.core.timeout import deadline
from dsh.cordis.utils import js_to_string

_DOT = '[^\r\n\u2028\u2029]'
_FOLD = str.maketrans({**{chr(cp):chr(cp+32) for cp in range(65,91)}, '\u017f':'s', '\u212a':'k'})


class FileResolutionFailure(Exception):
    name = 'FileResolutionFailure'
    def __init__(self, cause):
        self.message = 'DeepSeek Files API could not resolve a request image.'
        self.cause = cause
        super().__init__(self.message)


def _search(pattern, detail):
    # /iu canonicalizes the two non-ASCII characters that fold to ASCII.
    # ASCII word boundaries and all four JS line terminators remain explicit.
    return re.search(pattern, detail.translate(_FOLD), re.ASCII) is not None


def providerRejectedFileId(detail):
    file = _search(r'\bfile(?:[_ -]?(?:id|api|not[_ -]?found|deleted|expired))?', detail)
    missing = _search(r'(?:expired|not[_ -]?found|deleted|do(?:es)? not exist|not created under (?:this|your) account)', detail)
    invalid = _search(r'(?:invalid'+_DOT+r'{0,20}file[_ -]?(?:id|api)|file[_ -]?(?:id|api)'+_DOT+r'{0,20}invalid)', detail)
    return file and (missing or invalid)


def providerRejectedNormalizedImage(detail):
    return (_search(r'(?:unsupported|invalid|cannot read|failed to (?:decode|process))'+_DOT+r'{0,40}image', detail)
        or _search(r'image'+_DOT+r'{0,40}(?:unsupported|invalid|cannot be decoded)', detail))


@lru_cache(maxsize=1)
def _word_table():
    path=Path(__file__).resolve().parents[1]/'resources/file_id_word_unicode16.json'
    table=json.loads(path.read_text(encoding='utf-8'))['ranges']
    return [row[0] for row in table], [row[1] for row in table]


def _word(character):
    starts,ends=_word_table();cp=ord(character);index=bisect_right(starts,cp)-1
    return index >= 0 and cp <= ends[index]


def detailNamesFileId(detail, fileId):
    def units(value):
        raw=value.encode('utf-16-le','surrogatepass')
        return ''.join(chr(raw[index] | raw[index+1]<<8) for index in range(0,len(raw),2))
    # Source indexes a single UTF-16 code unit on each side of the match.
    detail,fileId=units(detail),units(fileId)
    index=detail.find(fileId)
    while index >= 0:
        end=index+len(fileId)
        if (index==0 or not _word(detail[index-1])) and (end==len(detail) or not _word(detail[end])):
            return True
        index=detail.find(fileId,index+1)
    return False


def _unique(files, key):
    values={}
    for file in files:values[key(file)]=file
    return list(values.values())


def _stale(files, detail):
    unique=_unique(files, lambda file:(file['version']['variantId'],file['fileId']))
    exact=[file for file in unique if detailNamesFileId(detail,file['fileId'])]
    return exact or unique


def _facts(file):
    version=file['version'];ref=version['attachment'];location=file['location']
    name=ref.get('name')
    if name is None:name=ref['attachmentId']
    return '"%s" at message %s, image %s (%s, 8-bit %s, %sx%s)' % (
        js_to_string(name),location['message'],location['image'],version['mediaType'],
        'sRGBA' if version['hasAlpha'] else 'sRGB',version['width'],version['height'])


def _diagnostic(files,message,detail):
    exact=next((file for file in files if detailNamesFileId(detail,file['fileId'])),None)
    target=exact if exact is not None else files[0] if len(files)==1 else None
    if target is not None:
        prefix='DeepSeek rejected normalized image %s: %s. ' % (_facts(target),message)
    else:
        candidates=_unique(files,lambda file:(file['version']['variantId'],file['location']['message'],file['location']['image']))
        prefix='DeepSeek rejected a normalized request image: %s. Candidate images: %s. ' % (message,'; '.join(_facts(file) for file in candidates))
    return prefix+'The provider rejected bytes already normalized by the harness; PNG, JPEG, WebP, and GIF remain supported input formats.'


class RequestFiles:
    def __init__(self,files,connection,policy,timeoutMs,signal,activity):
        self.files,self.connection,self.policy=files,connection,policy
        self.timeoutMs,self.signal,self.activity=timeoutMs,signal,activity
        self.used=[];self.retried=False

    def beginAttempt(self):
        self.used=[]

    async def resolve(self,version,location):
        with deadline(self.signal,self.timeoutMs,'DEEPSEEK_FILES_API_TIMEOUT') as limit:
            try:
                resolved=await self.files.ensureUploaded(version,self.connection,self.policy,limit.signal)
            except Exception as error:
                if self.signal.aborted:raise
                raise FileResolutionFailure(error) from error
            self.activity()
            self.used.append(dict(version=version,fileId=resolved['record']['fileId'],location=location))
            return resolved['record']['fileId']

    async def retry(self,detail):
        if not self.used or not providerRejectedFileId(detail):return False
        await self.files.invalidate([dict(variantId=file['version']['variantId'],fileId=file['fileId']) for file in _stale(self.used,detail)],self.connection)
        if self.retried:return False
        self.retried=True
        return True

    def errorMessage(self,status,message,detail):
        return _diagnostic(self.used,message,detail) if status==400 and self.used and providerRejectedNormalizedImage(detail) else message
