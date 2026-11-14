"""Pair staged custom-profile replacement and injected rename failures."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
TEMPLATES=['acp','web','headless','sdk','sdk-minimal']
CASES=[dict(template=name) for name in TEMPLATES]+[dict(mode=mode) for mode in ('existing','residual','twice','write','old-rename','new-rename','restore','concurrent','cleanup')]+[dict(name=name) for name in ('web','Web','HEADLESS','node_modules','../escape','')]+[dict(template=name) for name in ('unknown','toString')]


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(CASES),encoding='utf-8');return [path]


def snapshot(home):
    files={}
    for path in home.rglob('*'):
        if not path.is_file() or path.name=='.dsh-python.lock':continue
        name=re.sub(r'\.rescue\.staging-[^/]+','.rescue.staging-$ID',path.relative_to(home).as_posix())
        text=path.read_text(encoding='utf-8').replace('\r\n','\n')
        files[name]=json.loads(text) if path.name=='package.json' else text
    return files


def category(error):
    if error is None:return None
    text=str(error)
    for marker,value in [('could not be restored','restore'),('was recreated concurrently','concurrent'),('unknown default profile','unknown'),('names shipped profile','shipped'),('invalid profile','invalid'),('injected','injected')]:
        if marker in text:return value
    return type(error).__name__


async def native():
    import dsh.boot.profile_boot as launcher
    from dsh.boot.profile import init_profile,PROFILE_TEMPLATES
    result=[];raw=[]
    for index,case in enumerate(json.loads((OUTPUT/'input.json').read_text(encoding='utf-8'))):
        home=OUTPUT/'files/native'/str(index);home.mkdir(parents=True)
        name=case.get('name','rescue');mode=case.get('mode','new');directory=home/'profiles'/name
        if mode not in ('new','write'):
            directory.mkdir(parents=True)
            if mode!='residual':init_profile(str(directory),['old-bundle'],None)
            (directory/'old-marker').write_text('old',encoding='utf-8')
        original_rename=os.rename;original_remove=launcher.shutil.rmtree;original_init=launcher.init_profile
        def rename(source,target):
            source,target=str(source),str(target)
            if mode=='old-rename' and source==str(directory):raise OSError('injected old rename')
            if target==str(directory) and (mode=='restore' or (mode=='new-rename' and source.endswith(os.path.join('new',name)))):raise OSError('injected rename')
            if mode=='concurrent' and source.endswith(os.path.join('new',name)):
                original_init(str(directory),['concurrent-bundle'],None)
            return original_rename(source,target)
        def initialize(*args):
            if mode=='write':raise OSError('injected write')
            return original_init(*args)
        def remove(path,*args,**kwargs):
            if mode=='cleanup' and '.staging-' in str(path):raise OSError('injected cleanup')
            return original_remove(path,*args,**kwargs)
        warning=io.StringIO();error=None
        with patch.object(launcher,'PROFILE_TEMPLATES',{key:PROFILE_TEMPLATES[key] for key in TEMPLATES}),patch.object(launcher,'init_profile',initialize),patch.object(launcher.os,'rename',rename),patch.object(launcher.shutil,'rmtree',remove),contextlib.redirect_stderr(warning):
            try:
                launcher.initialize_profile_from_default(name,case.get('template','web'),str(home))
                if mode=='twice':launcher.initialize_profile_from_default(name,'headless',str(home))
            except Exception as failure:error=failure
        result.append(dict(case=index,error=category(error),members=len(getattr(error,'errors',[])),warning=bool(warning.getvalue()),files=snapshot(home)))
        raw.append(dict(case=index,error=None if error is None else str(error),warning=warning.getvalue()))
    (OUTPUT/'native-diagnostics.json').write_text(json.dumps(raw),encoding='utf-8');return result


if __name__=='__main__':
    probe.native=native;source=ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_profile_replace.mts','Actual staged profile replacement, template-only metadata, restore failures, concurrent winner and cleanup warnings.',
        [Path(__file__).resolve(),ROOT/'dsh/boot/profile_boot.py',ROOT/'dsh/boot/profile.py',ROOT/'dsh/boot/profile_lease.py',source/'apps/cli/src/profile-boot.ts',source/'packages/boot/app-boot/src/profile.ts'],prepare)
