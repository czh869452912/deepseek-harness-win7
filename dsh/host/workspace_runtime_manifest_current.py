"""Pinned primary-runtime metadata normalization and selected entry paths."""
import ntpath
import os
import re

from dsh.cordis.utils import _UNDEFINED

VERSION=re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9_.-]+)?\Z')
NAME=re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*\Z')
DISTRIBUTION=re.compile(r'[0-9][A-Za-z0-9_.!+\-]*\Z')


def _version(value):return isinstance(value,str) and VERSION.fullmatch(value) is not None


def parsePrimaryRuntime(value):
    def invalid():raise ValueError('primary runtime: invalid metadata')
    if not isinstance(value,dict):invalid()
    legacy=value.get('components',_UNDEFINED) is not _UNDEFINED
    versions=value['components'] if legacy else value
    if not isinstance(versions,dict) or legacy and any(value.get(key,_UNDEFINED) is not _UNDEFINED for key in ['python','node','pnpm']):invalid()
    desktop=value.get('desktopVersion');platform=value.get('platform');arch=value.get('arch')
    digest=value.get('payloadDigest',_UNDEFINED)
    python=versions.get('python',_UNDEFINED);node=versions.get('node',_UNDEFINED);pnpm=versions.get('pnpm',_UNDEFINED)
    packages=value.get('pythonPackages',{} if legacy else _UNDEFINED)
    if (not isinstance(desktop,str) or not desktop or platform not in ['win32','darwin','linux']
            or arch not in ['x64','arm64'] or not _version(python)
            or node is not _UNDEFINED and not _version(node)
            or pnpm is not _UNDEFINED and (not _version(pnpm) or node is _UNDEFINED)
            or digest is not _UNDEFINED and (not isinstance(digest,str) or re.fullmatch(r'[a-f0-9]{64}',digest) is None)
            or not isinstance(packages,dict)):invalid()
    distributions={}
    for name,version in packages.items():
        if not isinstance(name,str) or NAME.fullmatch(name) is None or not isinstance(version,str) or DISTRIBUTION.fullmatch(version) is None:invalid()
        normalized=re.sub('[-_.]+','-',name.lower())
        if normalized in distributions:invalid()
        distributions[normalized]=version
    if legacy:
        for name in ['numpy','pandas']:
            if not _version(versions.get(name,_UNDEFINED)):invalid()
            if name in distributions and distributions[name]!=versions[name]:
                raise ValueError('primary runtime: conflicting '+name+' distribution version')
    result=dict(desktopVersion=desktop,platform=platform,arch=arch)
    if digest is not _UNDEFINED:result['payloadDigest']=digest
    result['python']=python
    if node is not _UNDEFINED:result['node']=node
    if pnpm is not _UNDEFINED:result['pnpm']=pnpm
    result['pythonPackages']=packages
    return result


def _join(*parts):
    # Node join inserts separators even after a drive-only root (C:).
    if os.name=='nt':
        first=next((part for part in parts if part),'')
        joined='\\'.join(part for part in parts if part)
        if not re.match(r'^[\\/]{2}[^\\/]',first):joined=re.sub(r'^[\\/]{2,}',r'\\',joined)
        return ntpath.normpath(joined)
    return os.path.normpath('/'.join(part for part in parts if part))


def workspaceDependencyPaths(root,manifest):
    dependencies=_join(root,'dependencies');windows=manifest['platform']=='win32'
    result=dict(python=_join(dependencies,'python',*(['python.exe'] if windows else ['bin','python3'])))
    if manifest.get('node',_UNDEFINED) is not _UNDEFINED:
        result.update(node=_join(dependencies,'node','bin','node.exe' if windows else 'node'),
            nodePackages=_join(dependencies,'node','node_modules'))
    if manifest.get('pnpm',_UNDEFINED) is not _UNDEFINED:result['pnpm']=_join(dependencies,'pnpm','bin','pnpm.mjs')
    result['pythonPackages']=_join(dependencies,'python',*(['Lib'] if windows else ['lib','python'+'.'.join(manifest['python'].split('.')[:2])]),'site-packages')
    result['pythonDistributions']=manifest['pythonPackages']
    return result
