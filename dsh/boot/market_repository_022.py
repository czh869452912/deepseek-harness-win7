"""Repository identities from unchanged pinned hosted-git-info and Source helpers."""
from functools import lru_cache

from dsh.boot.market_index_022 import observe_market_operations


def _resolve(kind, value):
    row = observe_market_operations([dict(kind=kind, value=value)])[0]
    if not row['ok']:
        raise ValueError(row['error']['message'])
    return row['value']


@lru_cache(maxsize=1024)
def _repository(url):
    return _resolve('repository', url)


def repository_of(url):
    value = _repository(url)
    return None if value is None else dict(value)


def manifest_repository(value):
    return _resolve('manifest-repository', value)
