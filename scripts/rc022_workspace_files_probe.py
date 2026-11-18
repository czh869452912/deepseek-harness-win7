"""Real filesystem observations for fixed primary-runtime resolution/install."""
import asyncio
import errno
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from dsh.host import workspace_runtime_files_current as runtime
from dsh.host.workspace_runtime_manifest_current import workspaceDependencyPaths

WORKSPACE=None
SCENARIOS=['resolve','install','reuse','digest','recover','incomplete','wrong-python','wrong-packages',
 'bad-arch','bad-json','bad-installed-json','package-order','unknown-fields','root-link','previous-link',
 'manifest-link','payload-link','reuse-wrong-entry','recovery-incomplete','old-previous']


def prepare(output):
    global WORKSPACE
    workspace=Path(tempfile.mkdtemp(prefix='g-')).resolve()
    WORKSPACE=workspace/'native'
    (output/'pytest-workspace-mapping.json').write_text(json.dumps(dict(format='dsh-release-workspace@2',
        temporary_parent=str(workspace.parent),execution_path=str(workspace),retained_path=str(output/'files'),
        scope='Owned short paired filesystem workspace; retained after both consumers settle')),encoding='utf-8')
    path=output/'inputs.json'
    path.write_text(json.dumps(dict(directory=str(workspace/'source'),scenarios=SCENARIOS)),encoding='utf-8')
    return [path]


def junction(path,target):
    path.parent.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        result=subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(path),str(target)],capture_output=True)
        if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace'))
    else:os.symlink(str(target),str(path),target_is_directory=True)


async def observe(directory=None):
    directory=Path(directory or WORKSPACE or tempfile.mkdtemp(prefix='runtime-files-'))
    rows=[]
    for scenario in SCENARIOS:
        base=directory/scenario;source=base/'source';root=base/'home'/'runtime';outside=base/'outside'
        source.mkdir(parents=True);outside.mkdir();(outside/'keep').write_bytes(b'outside')
        manifest=dict(desktopVersion='fixture',platform=runtime._platform(),arch=runtime._arch(),python='3.8.10',
                      node='16.20.2',pnpm='8.15.9',pythonPackages={'NumPy':'1.24.4','Pillow':'10.4.0'})
        paths=workspaceDependencyPaths(str(source),manifest)
        for key in ['python','node','pnpm']:
            path=Path(paths[key]);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'interpreter')
        for key in ['pythonPackages','nodePackages']:Path(paths[key]).mkdir(parents=True)
        def write_manifest(value=manifest):
            (source/'runtime.json').write_text(json.dumps(value),encoding='utf-8')
        write_manifest()
        error=None;value=None
        try:
            if scenario in ['reuse','digest','recover','incomplete','bad-installed-json','package-order','unknown-fields',
                            'manifest-link','reuse-wrong-entry','recovery-incomplete','old-previous']:
                await runtime.installPrimaryRuntime(str(source),str(root))
                (root/'user-package').write_bytes(b'user')
            if scenario in ['recover','recovery-incomplete']:os.rename(str(root),str(root)+'.previous')
            if scenario in ['digest','incomplete','recovery-incomplete','old-previous']:
                manifest['payloadDigest']='a'*64;write_manifest()
            if scenario in ['incomplete','recovery-incomplete']:
                Path(paths['python']).unlink()
            if scenario=='wrong-python':Path(paths['python']).unlink();Path(paths['python']).mkdir()
            if scenario=='wrong-packages':
                Path(paths['pythonPackages']).rmdir();Path(paths['pythonPackages']).write_bytes(b'wrong')
            if scenario=='bad-arch':manifest['arch']='arm64' if manifest['arch']=='x64' else 'x64';write_manifest()
            if scenario=='bad-json':(source/'runtime.json').write_bytes(b'{')
            if scenario=='bad-installed-json':(root/'runtime.json').write_bytes(b'{')
            if scenario=='package-order':
                manifest['pythonPackages']={'Pillow':'10.4.0','NumPy':'1.24.4'};write_manifest()
            if scenario=='unknown-fields':write_manifest(dict(manifest,unknown=True))
            if scenario in ['root-link','previous-link']:
                junction(root if scenario=='root-link' else Path(str(root)+'.previous'),outside)
            if scenario=='manifest-link':
                (root/'runtime.json').unlink();junction(root/'runtime.json',outside)
            if scenario=='payload-link':junction(source/'extra',outside)
            if scenario=='reuse-wrong-entry':
                installed=Path(workspaceDependencyPaths(str(root),manifest)['python']);installed.unlink();installed.mkdir()
            if scenario=='old-previous':
                previous=Path(str(root)+'.previous');previous.mkdir();(previous/'stale').write_bytes(b'old')
            value=await (runtime.resolvePrimaryRuntime(str(source)) if scenario=='resolve' else runtime.installPrimaryRuntime(str(source),str(root)))
            value={key:entry.replace(str(base),'<base>').replace('\\','/') if isinstance(entry,str) else entry for key,entry in value.items()}
        except Exception as caught:
            (base/'failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
            if isinstance(caught,OSError):error=dict(code=errno.errorcode.get(caught.errno,str(caught.errno)))
            elif isinstance(caught,json.JSONDecodeError):error=dict(code='JSON_PARSE')
            else:error=dict(message=re.sub(r'\.primary-runtime-[^/]+','.primary-runtime-<staging>',str(caught).replace(str(base),'<base>').replace('\\','/')))
        def snapshot(path):
            if not path.exists() and not path.is_symlink():return None
            if runtime._link(os.lstat(str(path))):return 'link'
            if path.is_file():return path.read_bytes().decode('utf-8','replace')
            return {child.name:snapshot(child) for child in sorted(path.iterdir())}
        rows.append(dict(scenario=scenario,error=error,value=value,root=snapshot(root),previous=snapshot(Path(str(root)+'.previous')),
                         outside=snapshot(outside),staging=sorted(path.name for path in root.parent.glob('.primary-runtime-*'))))
        # Metadata serialization spacing belongs to the JSON carrier, not copied-byte parity.
        for key in ['root','previous']:
            if isinstance(rows[-1][key],dict) and isinstance(rows[-1][key].get('runtime.json'),str):
                text=rows[-1][key]['runtime.json']
                try:rows[-1][key]['runtime.json']=json.loads(text)
                except ValueError:pass
    return rows


if __name__=='__main__':
    probe.native=observe
    try:
        probe.main('rc022_workspace_files.mts',scope='Actual filesystem install/reuse/recovery/link safety and selected errors; OS failures compared by errno, JSON syntax by category; random staging basenames normalized.',prepare=prepare,
            extra_inputs=[ROOT/'dsh/host/workspace_runtime_files_current.py',ROOT/'dsh/host/workspace_runtime_manifest_current.py',Path(__file__).resolve(),
                          ROOT/'reference/packages/skill/tool-workspace-dependencies/src/index.ts'])
    finally:
        if WORKSPACE is not None:
            from scripts.verify_release import retain_regression_workspace
            output=Path(sys.argv[sys.argv.index('--output')+1]).resolve()
            retain_regression_workspace(WORKSPACE.parent,output/'files')
