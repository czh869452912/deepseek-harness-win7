"""Own preparation subprocesses and validate their publication before mutation."""
from contextlib import asynccontextmanager
import json
import os
import tempfile
from types import SimpleNamespace

from dsh.boot.python_package_cli import package_command
from dsh.boot.plugin_package_run import run_package_process
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot.python_plugins import reparse,validate_package,file_hashes
from dsh.boot.python_package_tarball import unpack_tarball


def read_prepared(directory,local=False,git_spec=None,url_spec=None):
    if sum((bool(local),git_spec is not None,url_spec is not None))>1:raise ValueError('preparation requires exactly one source kind')
    git=git_spec is not None
    remote=url_spec is not None
    receipt=os.path.join(directory,'prepared.json');archive=os.path.join(directory,'package.tgz')
    if reparse(directory) or reparse(receipt) or reparse(archive):raise ValueError('prepared package must not contain links')
    if os.path.getsize(receipt)>1024*1024:raise ValueError('prepared package receipt exceeds byte limit')
    with open(receipt,encoding='utf-8') as stream:value=json.load(stream)
    keys={'formatVersion','manifest','acquisition'} | ({'files','archive'} if local or git else set()) | ({'git'} if git else set())
    if not isinstance(value,dict) or set(value)!=keys or type(value['formatVersion']) is not int or value['formatVersion']!=(4 if remote else 3 if git else 2 if local else 1):
        raise ValueError('invalid prepared package receipt')
    if local or git:
        from dsh.boot.python_package_local import archive_record
        if value['acquisition'] is not None or value['archive']!=archive_record(archive):raise ValueError('local publication differs from its archive record')
        acquisition=None
        if git:
            from dsh.boot.python_package_git import git_source
            from dsh.boot.python_plugin_git_origin import checked_git_origin
            origin=value['git']
            if not isinstance(origin,dict) or set(origin)!={'repository','commit','directory'}:raise ValueError('invalid prepared Git origin')
            acquisition=dict(value['archive'],kind='git-tgz',**origin)
            actual=checked_git_origin(acquisition);expected=git_source(git_spec)
            if (actual['publicRepository']!=expected['publicRepository'] or actual['directory']!=expected['directory']
                    or len(expected['ref'])==40 and all(char in '0123456789abcdef' for char in expected['ref']) and actual['ref']!=expected['ref']):
                raise ValueError('prepared Git source differs from the requested identity')
            acquisition=verified_record(archive,acquisition)
    else:
        acquisition=verified_record(archive,value['acquisition'])
        if remote:
            from dsh.boot.python_package_tarball import artifact_url
            if acquisition is None or acquisition.get('kind')!='url-tgz' or acquisition['url']!=artifact_url(url_spec,public=True):
                raise ValueError('remote publication differs from the requested URL')
        elif acquisition is None or acquisition.get('kind')!='registry-tgz':raise ValueError('registry publication requires its acquisition identity')
    with tempfile.TemporaryDirectory(prefix='verify-',dir=os.path.dirname(directory)) as stage:
        unpack_tarball(archive,stage);manifest=validate_package(stage)
        matches=(file_hashes(stage)==value['files'] if local or git else True if remote else
            acquisition.get('name')==manifest['name'] and acquisition.get('version')==manifest['version'])
        if manifest!=value['manifest'] or not matches:
            raise ValueError('prepared package receipt differs from its archive')
    return SimpleNamespace(manifest=manifest,source=archive,acquisition=acquisition)


@asynccontextmanager
async def _prepared_package(directory,spec,options=None,local=False,git=False,remote=False):
    options=dict(options or {});root=os.path.join(directory,'.dsh-python-downloads')
    os.makedirs(root,exist_ok=True)
    if reparse(root):raise ValueError('native package preparation root must not be a link')
    command=package_command();registry=options.pop('registry',None)
    if local or git or remote:registry=None
    try:
        with tempfile.TemporaryDirectory(prefix='prepare-',dir=root) as owned:
            output=os.path.join(owned,'output');os.mkdir(output)
            workspace=None
            if git:
                from dsh.boot.python_package_git import create_git_workspace,cleanup_git_workspace
                workspace=create_git_workspace(owned)
            # A killed child cannot orphan downloads outside the owned root.
            env=dict(options.get('env') or {});env.update(TEMP=owned,TMP=owned,TMPDIR=owned)
            argv=[command['command']]+command['args']+['prepare-url' if remote else 'prepare-git' if git else 'prepare-local' if local else 'prepare',spec,output]+([workspace] if git else [])+([] if registry is None else ['--registry='+registry])
            # stdout JSON and stderr prose can arrive between each other's
            # writes, including between print's body and newline. Preserve the
            # ordinary merged log while parsing refusal metadata from stdout.
            stdout=bytearray();callback=options.get('onOutput')
            def received(text,stream):
                if stream=='stdout':
                    stdout.extend(text.encode('utf-8'))
                    if len(stdout)>1024*1024:del stdout[:-1024*1024]
                if callback is not None:callback(text,stream)
            try:
                result=await run_package_process(directory,argv,dict(options,env=env,onOutput=received,outputBytes=options.get('outputBytes',16384)))
            finally:
                if workspace is not None:cleanup_git_workspace(workspace)
            if result['exitCode']!=0 or result.get('timedOut'):
                for line in stdout.decode('utf-8',errors='replace').splitlines():
                    try:
                        error=json.loads(line).get('error',{})
                        if error.get('code')=='ERR_DSH_PLUGIN_INCOMPATIBLE' and isinstance(error.get('incompatible'),list):
                            result['incompatible']=error['incompatible']
                    except (ValueError,AttributeError):pass
                yield SimpleNamespace(result=result,candidate=None);return
            signal=options.get('signal')
            if signal is not None:signal.throwIfAborted()
            candidate=read_prepared(output,local=local,git_spec=spec if git else None,url_spec=spec if remote else None)
            yield SimpleNamespace(result=result,candidate=candidate)
    finally:
        try:os.rmdir(root)
        except OSError:pass  # Another owned preparation may still be active.


@asynccontextmanager
async def prepared_registry_package(directory,spec,options=None):
    async with _prepared_package(directory,spec,options) as prepared:
        yield prepared


@asynccontextmanager
async def prepared_local_package(directory,source,options=None):
    async with _prepared_package(directory,source,options,local=True) as prepared:
        yield prepared


@asynccontextmanager
async def prepared_git_package(directory,spec,options=None):
    async with _prepared_package(directory,spec,options,git=True) as prepared:
        yield prepared


@asynccontextmanager
async def prepared_url_package(directory,spec,options=None):
    async with _prepared_package(directory,spec,options,remote=True) as prepared:
        yield prepared
