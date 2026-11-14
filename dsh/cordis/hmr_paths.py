"""Filesystem roots bounding a profile's loaded modules."""
import os
import re
from urllib.parse import urlparse
from urllib.request import url2pathname


def file_path(url):
    parsed = urlparse(url)
    if parsed.scheme != 'file':
        raise ValueError('expected file URL')
    if re.search(r'%2f|%5c', parsed.path, re.I):
        raise ValueError('file URL cannot include encoded separators')
    path = url2pathname(parsed.path)
    return '//'+parsed.netloc+path if parsed.netloc else path


def profile_roots(directory):
    from dsh.boot.profile import is_symlink_or_junction
    if not os.path.exists(directory):
        raise FileNotFoundError(directory)
    real = os.path.realpath(directory)
    modules = os.path.join(real, 'node_modules')
    names = os.listdir(modules) if os.path.exists(modules) else []
    packages = []
    for name in names:
        package = os.path.join(modules, name)
        if name.startswith('@'):
            packages.extend(os.path.join(package, child) for child in os.listdir(package))
        else:
            packages.append(package)
    linked = [path for path in packages if is_symlink_or_junction(path) and os.path.exists(path)]
    return list(dict.fromkeys(os.path.realpath(path)+os.sep for path in [directory, *linked]))


def package_manifests(url, roots):
    manifests = []
    directory = os.path.dirname(file_path(url))
    while any((directory+os.sep).startswith(root) for root in roots):
        path = os.path.join(directory, 'package.json')
        if os.path.exists(path):
            manifests.append(path)
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    return manifests
