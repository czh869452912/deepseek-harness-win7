"""Integrity-pinned npm tarballs, bounded before any Python package is mounted."""
import base64
from contextlib import contextmanager
import gzip
import hashlib
from http.client import HTTPException
import os
import re
import tarfile
import tempfile
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,urlunsplit
from urllib.request import Request

from dsh.boot.python_package import inside,relative_parts
from dsh.boot.python_package_query import RegistryRedirects
from dsh.host.http_proxy import build_opener

MAX_BYTES=64*1024*1024
MAX_FILES=4096


def artifact_url(url,public=False):
    if not isinstance(url,str) or any(ord(char)<=32 or ord(char)==127 for char in url):raise ValueError('invalid package tarball URL')
    try:fields=urlsplit(url);port=fields.port
    except ValueError:raise ValueError('invalid package tarball URL') from None
    if fields.scheme not in ('http','https') or not fields.hostname or fields.username is not None or fields.password is not None or fields.fragment or port==0:
        raise ValueError('package tarball requires an HTTP(S) URL without credentials or fragments')
    return urlunsplit((fields.scheme,fields.netloc,fields.path,'' if public else fields.query,''))


def integrity_options(integrity):
    if not isinstance(integrity,str):raise ValueError('package tarball requires SHA-256 or SHA-512 integrity')
    choices={}
    for token in integrity.split():
        algorithm,separator,encoded=token.partition('-')
        if algorithm not in ('sha256','sha512') or not separator:continue
        try:value=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise ValueError('invalid package tarball integrity') from None
        if len(value)!=hashlib.new(algorithm).digest_size:raise ValueError('invalid package tarball integrity')
        choices.setdefault(algorithm,[]).append((value,algorithm+'-'+base64.b64encode(value).decode('ascii')))
    for algorithm in ('sha512','sha256'):
        if algorithm in choices:return algorithm,choices[algorithm]
    raise ValueError('package tarball requires SHA-256 or SHA-512 integrity')


@contextmanager
def downloaded_tarball(url,integrity,max_bytes=MAX_BYTES,timeout_seconds=90):
    artifact_url(url);algorithm,choices=integrity_options(integrity)
    if type(max_bytes) is not int or max_bytes<1 or not isinstance(timeout_seconds,(float,int)) or not 0<timeout_seconds<float('inf'):
        raise ValueError('package tarball limits must be positive and finite')
    request=Request(url,headers={'Accept-Encoding':'identity','User-Agent':'dsh-python-package/1'})
    with tempfile.TemporaryDirectory(prefix='dsh-native-package-') as temporary:
        path=os.path.join(temporary,'package.tgz');digest=hashlib.new(algorithm);sha256=hashlib.sha256();size=0;deadline=time.monotonic()+timeout_seconds
        try:
            with build_opener(RegistryRedirects()).open(request,timeout=min(15,timeout_seconds)) as response:
                artifact_url(response.geturl())
                if response.getcode()!=200 or response.headers.get('Content-Encoding','identity').lower()!='identity':raise ValueError('package tarball requires a complete unencoded 200 response')
                length=response.headers.get('Content-Length')
                if length is not None and (not re.fullmatch(r'[0-9]+',length.strip()) or int(length)>max_bytes):raise ValueError('package tarball exceeds byte limit')
                with open(path,'xb') as stream:
                    while True:
                        if time.monotonic()>=deadline:raise ValueError('package tarball download exceeded time limit')
                        chunk=response.read1(min(65536,max_bytes-size+1))
                        if not chunk:break
                        size+=len(chunk)
                        if size>max_bytes:raise ValueError('package tarball exceeds byte limit')
                        stream.write(chunk);digest.update(chunk);sha256.update(chunk)
                if length is not None and size!=int(length):raise ValueError('package tarball download is incomplete')
        except HTTPError as error:raise ValueError('package tarball download failed with status '+str(error.code)) from None
        except (URLError,OSError,HTTPException) as error:raise ValueError('package tarball download failed: '+type(error).__name__) from None
        matched=next((token for expected,token in choices if expected==digest.digest()),None)
        if matched is None:raise ValueError('package tarball integrity mismatch')
        yield path,dict(kind='registry-tgz',url=artifact_url(url,public=True),integrity=matched,sha256=sha256.hexdigest(),bytes=size)


def unpack_tarball(source,target,max_bytes=MAX_BYTES,max_files=MAX_FILES):
    """Never extract links or delegate path handling to tarfile.extractall."""
    if type(max_bytes) is not int or max_bytes<1 or type(max_files) is not int or max_files<1:raise ValueError('invalid package unpack limits')
    if os.path.lexists(target):
        info=os.lstat(target)
        if os.path.islink(target) or getattr(info,'st_file_attributes',0)&0x400 or not os.path.isdir(target) or os.listdir(target):raise ValueError('package unpack target must be an empty owned directory')
    # Bound decompressed headers/PAX data before tarfile allocates their payloads.
    raw_limit=max_bytes+(max_files+64)*1024
    with tempfile.TemporaryFile(dir=os.path.dirname(os.path.abspath(target))) as raw:
        try:
            with gzip.open(source,'rb') as incoming:
                size=0
                while True:
                    chunk=incoming.read(min(65536,raw_limit-size+1))
                    if not chunk:break
                    size+=len(chunk)
                    if size>raw_limit:raise ValueError('package tarball expanded stream exceeds byte limit')
                    raw.write(chunk)
            raw.seek(0)
            with tarfile.open(fileobj=raw,mode='r:') as archive:
                entries=[];seen=set();total=0;count=0;root_seen=False
                for entry in archive:
                    count+=1
                    if count>max_files:raise ValueError('package tarball has too many entries')
                    name=entry.name.rstrip('/') if entry.isdir() else entry.name
                    if name=='package' and entry.isdir():
                        if root_seen:raise ValueError('package tarball has duplicate root entries')
                        root_seen=True;continue
                    if not name.startswith('package/'):raise ValueError('package tarball must contain one package root')
                    relative=name[len('package/'):];relative_parts(relative);key=relative.casefold()
                    if key in seen or not (entry.isfile() or entry.isdir()) or entry.sparse is not None:raise ValueError('package tarball has duplicate or nonregular entries')
                    if entry.size<0:raise ValueError('package tarball has invalid member size')
                    seen.add(key);total+=entry.size
                    if total>max_bytes:raise ValueError('package tarball contents exceed byte limit')
                    entries.append((entry,relative))
                directories={relative.casefold():entry.isdir() for entry,relative in entries}
                if directories.get('package.json',True):raise ValueError('package tarball has no regular manifest')
                for key in directories:
                    parts=key.split('/')
                    if any('/'.join(parts[:index]) in directories and not directories['/'.join(parts[:index])] for index in range(1,len(parts))):
                        raise ValueError('package tarball has conflicting path ancestors')
                for entry,relative in entries:
                    destination=inside(target,relative)
                    if entry.isdir():os.makedirs(destination,exist_ok=True);continue
                    os.makedirs(os.path.dirname(destination),exist_ok=True)
                    with archive.extractfile(entry) as incoming,open(destination,'xb') as outgoing:
                        remaining=entry.size
                        while remaining:
                            chunk=incoming.read(min(65536,remaining))
                            if not chunk:raise ValueError('package tarball member is incomplete')
                            outgoing.write(chunk);remaining-=len(chunk)
        except (tarfile.TarError,OSError,EOFError) as error:raise ValueError('invalid package tarball: '+type(error).__name__) from None
    return target
