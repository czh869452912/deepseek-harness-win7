"""Loaded module file identities used by profile hot replacement."""
import os
import re
import shutil
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import url2pathname

TIMESTAMP_RESOLUTION_MS = 2000


def _identity_of(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme != 'file' or re.search(r'%2f|%5c', parsed.path, re.I):
            return None
        path = url2pathname(parsed.path)
        if parsed.netloc:
            path = '//'+parsed.netloc+path
        information = os.stat(path)
    except (OSError, ValueError):
        return None
    seconds, nanos = divmod(information.st_mtime_ns, 1000000000)
    modified_at = seconds*1000+nanos/1000000.0
    # Node's normal Stats fields are doubles; ctime is deliberately excluded.
    return (float(information.st_ino), information.st_size, modified_at), modified_at


class ModuleFiles:
    def __init__(self):
        self._records = {}
        self._observed_at = int(time.time()*1000)

    def now(self):
        try:
            directory = tempfile.mkdtemp(prefix='dsh-hmr-clock-')
        except OSError:
            return int(time.time()*1000)
        try:
            marker = os.path.join(directory, 'now')
            with open(marker, 'w', encoding='utf-8') as stream:
                stream.write('')
            information = os.stat(marker)
            seconds, nanos = divmod(information.st_mtime_ns, 1000000000)
            return seconds*1000+nanos/1000000.0
        finally:
            shutil.rmtree(directory)

    def compare(self, urls):
        stale, seen = set(), {}
        for url in urls:
            identity = _identity_of(url)
            seen[url] = None if identity is None else identity[0]
            if identity is None or (self._records[url] != identity[0] if url in self._records else identity[1] >= self._observed_at-TIMESTAMP_RESOLUTION_MS):
                stale.add(url)
        return dict(stale=stale, seen=seen)

    def observe(self, urls, options=None):
        options = options or {}
        seen, retained = options.get('seen', {}), options.get('retained', set())
        at = options['at'] if 'at' in options else self.now()
        records = {}
        for url in urls:
            if url in retained:
                records[url] = self._records.get(url)
            elif url in seen:
                records[url] = seen[url]
            else:
                identity = _identity_of(url)
                records[url] = None if identity is None or identity[1] > at else identity[0]
        self._records = records
        self._observed_at = at

    def refresh(self, urls):
        for url in urls:
            identity = _identity_of(url)
            self._records[url] = None if identity is None else identity[0]
