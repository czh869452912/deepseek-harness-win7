"""Fetch a pinned HTTPS ZIP; installation still belongs to the local store."""
from contextlib import contextmanager
import hashlib
from http.client import HTTPException
import os
import re
import tempfile
import time
import zipfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dsh.boot.python_plugins import MAX_BYTES

REQUEST_TIMEOUT = 15
DOWNLOAD_SECONDS = 90
CHUNK_BYTES = 64 * 1024


def checked_url(url):
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError('invalid HTTPS plugin URL')
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ValueError('invalid HTTPS plugin URL') from None
    if (parts.scheme != 'https' or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.fragment or port == 0):
        raise ValueError('plugin acquisition requires HTTPS without URL credentials or fragments')
    return parts


def public_url(url):
    parts = checked_url(url)
    # Asset redirects and signed download URLs may contain expiring credentials.
    # The archive hash is the reproducible identity, not the query string.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))


def checked_digest(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('HTTPS plugin acquisition requires a 64-digit SHA-256')
    return value.lower()


class HttpsRedirects(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, response, code, message, headers, url):
        checked_url(url)
        return super().redirect_request(request, response, code, message, headers, url)


@contextmanager
def downloaded_zip(url, sha256):
    checked_url(url)
    expected = checked_digest(sha256)
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    request = Request(url, headers={'Accept-Encoding': 'identity', 'User-Agent': 'dsh-python-plugin/1'})
    with tempfile.TemporaryDirectory(prefix='dsh-plugin-download-') as temporary:
        path = os.path.join(temporary, 'release.zip')
        digest, size = hashlib.sha256(), 0
        try:
            with build_opener(HttpsRedirects()).open(request, timeout=REQUEST_TIMEOUT) as response:
                checked_url(response.geturl())
                if response.getcode() != 200:
                    raise ValueError('HTTPS plugin download requires a complete 200 response')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('HTTPS plugin ZIP must not use HTTP content encoding')
                length = response.headers.get('Content-Length')
                if length is not None:
                    if not re.fullmatch(r'[0-9]+', length.strip()):
                        raise ValueError('invalid plugin download Content-Length')
                    length = int(length)
                    if length > MAX_BYTES:
                        raise ValueError('plugin download exceeds byte limit')
                with open(path, 'xb') as stream:
                    while True:
                        if time.monotonic() >= deadline:
                            raise ValueError('plugin download exceeded time limit')
                        chunk = response.read(CHUNK_BYTES)
                        if time.monotonic() >= deadline:
                            raise ValueError('plugin download exceeded time limit')
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise ValueError('plugin download exceeds byte limit')
                        stream.write(chunk)
                        digest.update(chunk)
                if length is not None and size != length:
                    raise ValueError('plugin download is incomplete')
        except HTTPError as error:
            raise ValueError('HTTPS plugin download failed with status {}'.format(error.code)) from None
        except (URLError, OSError, HTTPException) as error:
            raise ValueError('HTTPS plugin download failed: ' + type(error).__name__) from None
        if digest.hexdigest() != expected:
            raise ValueError('plugin download SHA-256 differs from the pinned archive')
        if not zipfile.is_zipfile(path):
            raise ValueError('HTTPS plugin source must be a ZIP')
        yield path, dict(kind='https-zip', url=public_url(url), sha256=expected, bytes=size)


def verified_record(source, record):
    """Tie persisted acquisition metadata to the actual installation container."""
    if record is None:
        return None
    if (not isinstance(record, dict) or set(record) != {'kind', 'url', 'sha256', 'bytes'}
            or record['kind'] != 'https-zip' or public_url(record['url']) != record['url']
            or type(record['bytes']) is not int or not 0 < record['bytes'] <= MAX_BYTES):
        raise ValueError('invalid plugin acquisition record')
    expected = checked_digest(record['sha256'])
    digest, size = hashlib.sha256(), 0
    with open(source, 'rb') as stream:
        while True:
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError('plugin download exceeds byte limit')
            digest.update(chunk)
    if size != record['bytes'] or digest.hexdigest() != expected:
        raise ValueError('plugin acquisition record differs from its source archive')
    return dict(record, sha256=expected)
