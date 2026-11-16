"""Private native package-command adapter used by the current management seam."""
import json
import os
from pathlib import Path
import sys
import shutil

# Executed by absolute filename from a profile, including embedded Python.
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))

from dsh.boot.plugin_registry_policy import UNSPECIFIED
from dsh.boot.python_package_query import (PackageQueryError,npm_configuration,
    configured_registry,query_metadata)


def package_command(env=None):
    options=dict(command=str(Path(sys.executable).resolve()),args=[str(Path(__file__).resolve())])
    if env is not None:options['env']=dict(env)
    return options


def _view(argv,directory):
    if len(argv)<2:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','view requires a package spec')
    spec=argv[1];fields=[];registry=None
    for argument in argv[2:]:
        if argument.startswith('--registry='):registry=argument[len('--registry='):]
        elif argument in ('--json','--config.fetch-retries=0'):continue
        elif argument.startswith('-'):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','unsupported metadata option')
        else:fields.append(argument)
    if not fields:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','metadata fields are required')
    return query_metadata(directory,spec,fields,registry)


def _prepare(argv,directory):
    from dsh.boot.python_package_acquire import acquired_registry_package
    from dsh.boot.profile_compatibility import read_profile_version_exemptions
    from dsh.boot.python_plugins import reparse,atomic_bytes,json_bytes
    if len(argv)<3:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','prepare requires a spec and owned output directory')
    spec,target=argv[1:3];registry=None
    for argument in argv[3:]:
        if argument.startswith('--registry='):registry=argument[len('--registry='):]
        else:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','unsupported package preparation option')
    if not os.path.isdir(target) or reparse(target) or os.listdir(target):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','package preparation output must be an empty owned directory')
    print('Fetching '+spec,flush=True)
    with acquired_registry_package(directory,spec,registry,exemptions=read_profile_version_exemptions(directory)) as candidate:
        shutil.copyfile(candidate.source,os.path.join(target,'package.tgz'))
        atomic_bytes(os.path.join(target,'prepared.json'),json_bytes(dict(formatVersion=1,manifest=candidate.manifest,acquisition=candidate.acquisition)))
        print('Prepared '+candidate.manifest['name']+'@'+candidate.manifest['version'],flush=True)


def _prepare_local(argv,directory):
    from dsh.boot.python_package_local import publish_local
    from dsh.boot.python_plugins import reparse
    if len(argv)!=3 or not os.path.isabs(argv[1]):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','prepare-local requires an absolute local source and owned output directory')
    source,target=argv[1:]
    if not os.path.isdir(target) or reparse(target) or os.listdir(target):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','package preparation output must be an empty owned directory')
    print('Preparing local native package',flush=True)
    manifest=publish_local(directory,source,target)
    print('Prepared '+manifest['name']+'@'+manifest['version'],flush=True)


def _prepare_git(argv,directory):
    from dsh.boot.python_package_git import publish_git
    from dsh.boot.python_plugins import reparse
    if len(argv)!=4:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','prepare-git requires a spec, owned output and Git workspace')
    spec,target,workspace=argv[1:]
    if not os.path.isdir(target) or reparse(target) or os.listdir(target):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','package preparation output must be an empty owned directory')
    manifest=publish_git(directory,spec,target,workspace)
    print('Prepared '+manifest['name']+'@'+manifest['version'],flush=True)


def _prepare_url(argv,directory):
    from dsh.boot.python_package_url import publish_url
    from dsh.boot.python_plugins import reparse
    if len(argv)!=3:raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','prepare-url requires a URL and owned output directory')
    spec,target=argv[1:]
    if not os.path.isdir(target) or reparse(target) or os.listdir(target):raise PackageQueryError('ERR_DSH_PACKAGE_ARGUMENT','package preparation output must be an empty owned directory')
    print('Fetching remote native tarball',flush=True)
    manifest=publish_url(directory,spec,target)
    print('Prepared '+manifest['name']+'@'+manifest['version'],flush=True)


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    try:
        if argv==['config','get','registry']:
            print(configured_registry(npm_configuration(os.getcwd())));return 0
        if argv and argv[0]=='view':
            value=_view(argv,os.getcwd())
            if value is not UNSPECIFIED:print(json.dumps(value,ensure_ascii=False,separators=(',',':')))
            return 0
        if argv and argv[0]=='prepare':_prepare(argv,os.getcwd());return 0
        if argv and argv[0]=='prepare-local':_prepare_local(argv,os.getcwd());return 0
        if argv and argv[0]=='prepare-git':_prepare_git(argv,os.getcwd());return 0
        if argv and argv[0]=='prepare-url':_prepare_url(argv,os.getcwd());return 0
        raise PackageQueryError('ERR_DSH_PYTHON_PACKAGE_OPERATION_UNAVAILABLE','native package mutation is not available in this query adapter')
    except PackageQueryError as error:
        details=dict(code=error.code,message=error.message)
        if getattr(error,'incompatible',None) is not None:details['incompatible']=error.incompatible
        print(json.dumps(dict(error=details),ensure_ascii=False))
        print(str(error),file=sys.stderr);return 1
    except Exception as error:
        # Never print an exception body containing configured URLs or secrets.
        code='ERR_DSH_PACKAGE_QUERY';message='native package query failed: '+type(error).__name__
        print(json.dumps(dict(error=dict(code=code,message=message))))
        print(code+' '+message,file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
