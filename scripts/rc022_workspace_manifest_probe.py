"""Fixed Source primary-runtime metadata and path observations."""
import asyncio
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def manifest():return dict(desktopVersion='fixture',platform='win32',arch='x64',python='3.8.10',pythonPackages={'NumPy':'1.24.4'})


def cases():
    base=manifest();rows=[dict(value=base)]
    values=[None,False,0,1,'','value',[],{},'1.2.3','1.2.3\n','1.2.3-alpha_1','1.2.3+build','1.2.3-alpha+build','\u0661.2.3']
    for field in ['desktopVersion','platform','arch','python','node','pnpm','pythonPackages','payloadDigest','components']:
        for value in values:rows.append(dict(value=dict(base,**{field:value})))
        omitted=dict(base);omitted.pop(field,None);rows.append(dict(value=omitted))
    for value in [None,False,1,'',[],[base]]:rows.append(dict(value=value))
    for key in ['numpy','NumPy','a_b','a.b','a-b','0','constructor','__proto__','a\n','a/b','a b','\u00e9']:
        for version in ['1.2.3','1!2.3+local','1rc1','v1','1\n','\u0661','']:
            rows.append(dict(value=dict(base,pythonPackages={key:version})))
    for packages in [{'A-b':'1','a_b':'1'},{'a.b':'1','A--B':'2'},{'NumPy':'1.2.3'},{}]:
        for numpy in ['1.2.3','1.2.4',None]:
            legacy={key:value for key,value in base.items() if key!='python'}
            legacy.update(components=dict(python='3.8.10',numpy=numpy,pandas='2.0.3'),pythonPackages=packages)
            rows.append(dict(value=legacy))
    for platform in ['win32','darwin','linux']:
        for root in ['C:\\runtime','C:','/runtime','//server/share','//','///server/share','relative/../runtime','',r'\\server\share\runtime']:
            for extras in [{},dict(node='16.20.2'),dict(node='16.20.2',pnpm='8.15.9')]:
                rows.append(dict(value=dict(base,platform=platform,**extras),root=root))
    for platform in ['win32','darwin','linux']:
        for arch in ['x64','arm64']:
            rows.append(dict(value=dict(base,platform=platform,arch=arch,payloadDigest='a'*64)))
    for version in ['01.002.3','1.2.3-','1.2.3+','1.2.3-..','0.0.0']:
        rows.append(dict(value=dict(base,python=version)))
    legacy={key:value for key,value in base.items() if key not in ['python','pythonPackages']}
    legacy['components']=dict(python='3.8.10',numpy='1.24.4',pandas='2.0.3')
    rows.append(dict(value=legacy))
    for key in ['python','node','pnpm']:rows.append(dict(value=dict(legacy,**{key:'1.2.3'})))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


async def observe():
    from dsh.host.workspace_runtime_manifest_current import parsePrimaryRuntime,workspaceDependencyPaths
    from dsh.cordis.json_text import stringify_json
    rows=[]
    for entry in cases():
        value=copy.deepcopy(entry['value'])
        try:
            parsed=parsePrimaryRuntime(value);row=dict(value=parsed)
            if 'root' in entry:row['paths']=workspaceDependencyPaths(entry['root'],parsed)
            rows.append(json.loads(stringify_json(row)))
        except Exception as error:rows.append(dict(error=str(error)))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_workspace_manifest.mts','Actual fixed Source primary-runtime metadata parser and path derivation versus Native adapter; legacy normalization, distribution collisions, selected fields and Windows-host path syntax. No payload install or process execution claim.',
        [Path(__file__).resolve(),ROOT/'dsh/host/workspace_runtime_manifest_current.py'],prepare=prepare)
