"""Pair read-only package tables, actual dependency graphs and successors."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
MODES=('installation','profile','other-profile','synthetic','optional','skipped-invalid','invalid','linked','refresh-installation','refresh-profile')


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(MODES),encoding='utf-8');return [path]


def package(path,name,version='1.0.0',**fields):
    path.mkdir(parents=True,exist_ok=True)
    (path/'package.json').write_text(json.dumps(dict(name=name,version=version,**fields)),encoding='utf-8')
    return path/'package.json'


def fixture(directory,mode):
    home=directory/'home';anchor=package(directory/'installation','installation',dependencies={'core':'*','uninstalled':'*'},peerDependencies={'peer':'*'})
    package(anchor.parent/'node_modules/core','core',dependencies={'shared':'*'},optionalDependencies={'extra':'*'})
    package(anchor.parent/'node_modules/peer','peer')
    package(anchor.parent/'node_modules/shared','shared')
    package(anchor.parent/'node_modules/extra','extra')
    if mode in ('invalid','skipped-invalid'):
        (anchor.parent/'node_modules/core/package.json').write_text('{',encoding='utf-8')
    profile_dir=home/'profiles'/'active'
    layers=[]
    if mode not in ('installation','refresh-installation'):
        if mode!='synthetic':package(profile_dir,'profile',dependencies={'selected':'*','direct':'*'},peerDependencies={'direct':'*'},optionalDependencies={'optional':'*'},dsh=dict(profile=dict(bundles=['selected'])))
        else:profile_dir.mkdir(parents=True)
        selected=profile_dir/'node_modules/selected'
        package(selected,'selected',dependencies={'private':'*','shared':'*'},dsh=dict(bundle=dict(patch='./patch.yml')))
        (selected/'patch.yml').write_text('[]',encoding='utf-8')
        package(selected/'node_modules/private','private',dependencies={'grandchild':'*'})
        package(selected/'node_modules/shared','shared','99.0.0')
        package(selected/'node_modules/grandchild','grandchild')
        package(profile_dir/'node_modules/direct','direct')
        package(profile_dir/'node_modules/optional','optional')
        second=directory/'second';package(second,'second',dependencies={'private':'*','second-only':'*'})
        package(second/'node_modules/private','private','99.0.0')
        package(second/'node_modules/second-only','second-only')
        layers=[dict(packageName='selected',packageDir=str(selected),patchPaths=[],patches=[]),dict(packageName='second',packageDir=str(second),patchPaths=[],patches=[])]
        if mode=='other-profile':layers.reverse()
        if mode=='optional':layers=[]
    if mode=='linked':
        from dsh.boot.profile import create_symlink
        external=directory/'external';package(external,'external')
        internal=profile_dir/'inside';internal.mkdir()
        sibling=home/'profiles/sibling';sibling.mkdir()
        create_symlink(str(external),str(profile_dir/'node_modules/linked'))
        create_symlink(str(internal),str(profile_dir/'node_modules/inside'))
        create_symlink(str(sibling),str(profile_dir/'node_modules/sibling'))
        # Win7-compatible CreateJunction needs a live target during creation.
        missing=directory/'missing';missing.mkdir()
        create_symlink(str(missing),str(profile_dir/'node_modules/dangling'));missing.rmdir()
    profile=None if mode in ('installation','refresh-installation') else dict(name='active',dir=str(profile_dir),layers=layers,skippedBundles=[dict(packageName='core',reason='invalid')] if mode=='skipped-invalid' else [])
    return dict(installAnchor=str(anchor),home=str(home),profile=profile)


def files(directory):
    # Avoid traversing links when checking the read-only table constructor.
    import os
    result={}
    from dsh.boot.profile import is_symlink_or_junction
    for parent,dirs,names in os.walk(str(directory),followlinks=False):
        dirs[:]=[name for name in dirs if not is_symlink_or_junction(str(Path(parent)/name))]
        for name in names:
            path=Path(parent)/name
            if not path.is_symlink():result[str(path)]=path.read_bytes()
    return result


async def native():
    from dsh.boot.runtime_resolution import create_runtime_resolution
    result=[]
    for mode in MODES:
        directory=OUTPUT/'files'/'native'/mode;options=fixture(directory,mode);before=files(directory)
        try:resolution=await create_runtime_resolution(options)
        except Exception as error:
            result.append(dict(mode=mode,error=True,unchanged=files(directory)==before));continue
        row=dict(mode=mode,error=False,unchanged=files(directory)==before,table=resolution.to_dict())
        if mode.startswith('refresh-'):
            old=resolution.to_dict()
            if mode=='refresh-installation':package(directory/'installation/node_modules/uninstalled','uninstalled')
            else:
                selected=Path(options['profile']['dir'])/'node_modules/selected'
                manifest=json.loads((selected/'package.json').read_text(encoding='utf-8'));manifest['dependencies']['new-private']='*'
                (selected/'package.json').write_text(json.dumps(manifest),encoding='utf-8');package(selected/'node_modules/new-private','new-private')
            successor=await resolution.compute_latest_resolution()
            row.update(successor=successor.to_dict(),old_unchanged=resolution.to_dict()==old)
        result.append(json.loads(json.dumps(row).replace(str(directory).replace('\\','\\\\'),'$ROOT')))
    return result


if __name__=='__main__':
    probe.native=native
    probe.main('rc022_resolution.mts','Read-only immutable package generation construction and recomputation; not runtime import interception.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/runtime_resolution.py',ROOT/'reference/packages/boot/app-boot/src/profile.ts'],prepare)
