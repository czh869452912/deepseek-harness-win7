"""Own preparation subprocesses and validate their publication before mutation."""
from contextlib import asynccontextmanager
import json
import os
import tempfile
from types import SimpleNamespace

from dsh.boot.python_package_cli import package_command
from dsh.boot.plugin_package_run import run_package_process
from dsh.boot.python_plugin_acquisition import verified_record
from dsh.boot.python_plugins import reparse,validate_package
from dsh.boot.python_package_tarball import unpack_tarball


def read_prepared(directory):
    receipt=os.path.join(directory,'prepared.json');archive=os.path.join(directory,'package.tgz')
    if reparse(directory) or reparse(receipt) or reparse(archive):raise ValueError('prepared package must not contain links')
    if os.path.getsize(receipt)>1024*1024:raise ValueError('prepared package receipt exceeds byte limit')
    with open(receipt,encoding='utf-8') as stream:value=json.load(stream)
    if not isinstance(value,dict) or set(value)!= {'formatVersion','manifest','acquisition'} or type(value['formatVersion']) is not int or value['formatVersion']!=1:
        raise ValueError('invalid prepared package receipt')
    acquisition=verified_record(archive,value['acquisition'])
    with tempfile.TemporaryDirectory(prefix='verify-',dir=os.path.dirname(directory)) as stage:
        unpack_tarball(archive,stage);manifest=validate_package(stage)
        if manifest!=value['manifest'] or acquisition.get('name')!=manifest['name'] or acquisition.get('version')!=manifest['version']:
            raise ValueError('prepared package receipt differs from its archive')
    return SimpleNamespace(manifest=manifest,source=archive,acquisition=acquisition)


@asynccontextmanager
async def prepared_registry_package(directory,spec,options=None):
    options=dict(options or {});root=os.path.join(directory,'.dsh-python-downloads')
    os.makedirs(root,exist_ok=True)
    if reparse(root):raise ValueError('native package preparation root must not be a link')
    command=package_command();registry=options.pop('registry',None)
    try:
        with tempfile.TemporaryDirectory(prefix='prepare-',dir=root) as owned:
            output=os.path.join(owned,'output');os.mkdir(output)
            # A killed child cannot orphan downloads outside the owned root.
            env=dict(options.get('env') or {});env.update(TEMP=owned,TMP=owned,TMPDIR=owned)
            argv=[command['command']]+command['args']+['prepare',spec,output]+([] if registry is None else ['--registry='+registry])
            result=await run_package_process(directory,argv,dict(options,env=env,outputBytes=options.get('outputBytes',16384)))
            if result['exitCode']!=0 or result.get('timedOut'):
                yield SimpleNamespace(result=result,candidate=None);return
            signal=options.get('signal')
            if signal is not None:signal.throwIfAborted()
            candidate=read_prepared(output)
            yield SimpleNamespace(result=result,candidate=candidate)
    finally:
        try:os.rmdir(root)
        except OSError:pass  # Another owned preparation may still be active.
