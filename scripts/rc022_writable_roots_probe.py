"""Physical directories and Windows junction aliases through actual root helpers."""
import json
import re
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe():
    import _winapi
    from dsh.sandbox.roots_current import canonical_path,workspace_writable_roots,writable_roots
    base=WORKSPACE/'native';base.mkdir();workspace=base/'workspace';extra=base/'Memory';workspace.mkdir();extra.mkdir();file=base/'file';file.write_text('data',encoding='utf-8');alias=base/'alias';_winapi.CreateJunction(str(extra),str(alias));rows=[]
    def normalize(value):
        if isinstance(value,str):return value.replace(json.dumps(str(base))[1:-1],'<root>').replace(str(base),'<root>')
        if isinstance(value,list):return [normalize(item) for item in value]
        if isinstance(value,dict):return {key:normalize(item) for key,item in value.items()}
        return value
    try:
        rows.append(dict(name='canonical',existing=canonical_path(str(workspace)),alias=canonical_path(str(alias)),missing=canonical_path(str(base/'missing'))))
        for name,policy in (
            ('workspace',dict(mode='workspace-write',workspaceRoot=str(workspace))),
            ('extras',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(extra),str(extra)])),
            ('case-and-separator',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(extra).lower().replace('\\','/'),str(extra)])),
            ('workspace-duplicate',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(workspace)])),
            ('missing',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(base/'missing')])),
            ('file',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(file)])),
            ('junction',dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(alias)])),
            ('readonly-invalid',dict(mode='read-only',workspaceRoot=str(workspace),additionalWritableRoots=[str(base/'missing')])),
            ('full-invalid',dict(mode='danger-full-access',workspaceRoot=str(workspace),additionalWritableRoots=[str(alias)]))):
            try:rows.append(dict(name=name,workspace=workspace_writable_roots(policy),all=writable_roots(policy)))
            except Exception as error:
                print(json.dumps(dict(name=name,code=error.code,message=error.message)),file=sys.stderr)
                rows.append(dict(name=name,error=dict(code=error.code,message=re.sub(r'cannot read the directory: .*','cannot read the directory: <platform diagnostic>',error.message))))
        extra.rmdir()
        try:workspace_writable_roots(dict(mode='workspace-write',workspaceRoot=str(workspace),additionalWritableRoots=[str(extra)]))
        except Exception as error:rows.append(dict(name='revalidate',code=error.code))
        return normalize(rows)
    finally:alias.rmdir()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.txt';path.write_text(str(WORKSPACE),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_writable_roots.mts','Actual Windows physical root helpers: conservative workspace resolution, additional directory deduplication, casing/separators, missing/non-directory/junction rejection, repeat-time revalidation, read-only/full early return. Missing-root platform diagnostic bodies are normalized; raw full diagnostics are retained in stderr. Windows junction fixture avoids unavailable file symlink privilege.',[Path(__file__).resolve(),ROOT/'dsh/sandbox/roots_current.py',ROOT/'dsh/sandbox/policy_current.py'],prepare=prepare)
