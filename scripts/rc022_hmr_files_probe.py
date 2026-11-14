"""Pair disk-backed HMR observation, retained records and coarse clock edges."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None
BASE=1700000000000
STEPS=[
 dict(op='write',name='a',text='a',at=BASE-10000),dict(op='write',name='b',text='b',at=BASE),dict(op='write',name='c',text='c',at=BASE+1),
 dict(op='observe',names=[],at=BASE),dict(op='compare',names=['a','b','c','missing','node:fs']),
 dict(op='observe',names=['a','b','c','missing'],at=BASE),dict(op='compare',names=['a','b','c','missing']),
 dict(op='refresh',names=['c']),dict(op='compare',names=['a','b','c','missing']),
 dict(op='write',name='a',text='changed-size',at=BASE-10000),dict(op='compare',names=['a','b','c','missing']),
 dict(op='write',name='b',text='changed-b',at=BASE),dict(op='observe',names=['a','b','c','missing'],seen=True,at=BASE+20),dict(op='compare',names=['a','b','c','missing']),
 dict(op='write',name='c',text='changed-c',at=BASE+30),dict(op='observe',names=['a','b','c'],retained=['b','c'],at=BASE+40),dict(op='compare',names=['a','b','c','missing']),
 dict(op='write',name='old',text='o',at=BASE+40-2001),dict(op='write',name='edge',text='e',at=BASE+40-2000),dict(op='compare',names=['old','edge']),
 dict(op='observe',names=['old','edge'],retained=['old','edge'],at=BASE+40),dict(op='compare',names=['old','edge']),
 dict(op='refresh',names=['old']),dict(op='compare',names=['old','edge']),
 dict(op='observe',names=['a'],at=BASE+40),dict(op='compare',names=['a']),dict(op='link',name='a',to='hardlink'),dict(op='compare',names=['a']),
 dict(op='replace',name='a',text='changed-size',at=BASE-10000),dict(op='compare',names=['a']),
 dict(op='unlink',name='a'),dict(op='compare',names=['a']),dict(op='refresh',names=['a']),dict(op='compare',names=['a']),
 dict(op='write',name='at-tick',text='t',at=BASE+100),dict(op='write',name='after-tick',text='t',at=BASE+101),
 dict(op='observe',names=['at-tick','after-tick'],at=BASE+100),dict(op='compare',names=['at-tick','after-tick']),
]


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(STEPS),encoding='utf-8');return [path]


async def native():
    from dsh.cordis.hmr_files import ModuleFiles
    directory=OUTPUT/'files/native';directory.mkdir(parents=True)
    tracker=ModuleFiles();seen={};result=[]
    def url(name):return name if name.startswith('node:') else (directory/name).as_uri()
    for index,step in enumerate(json.loads((OUTPUT/'input.json').read_text(encoding='utf-8'))):
        op=step['op'];names=[url(name) for name in step.get('names',[])]
        if op in ('write','replace'):
            path=directory/step['name']
            if op=='replace':path.unlink()
            path.write_text(step['text'],encoding='utf-8');os.utime(str(path),ns=(step['at']*1000000,step['at']*1000000))
        elif op=='unlink':(directory/step['name']).unlink()
        elif op=='link':os.link(str(directory/step['name']),str(directory/step['to']))
        elif op=='observe':
            options=dict(at=step['at'],retained=set(url(name) for name in step.get('retained',[])))
            if step.get('seen'):options['seen']=seen
            tracker.observe(names,options)
        elif op=='refresh':tracker.refresh(names)
        elif op=='compare':
            value=tracker.compare(names);seen=value['seen']
            result.append(dict(step=index,stale=[name for name in step['names'] if url(name) in value['stale']],present={name:seen[url(name)] is not None for name in step['names']}))
    return result


if __name__=='__main__':
    probe.native=native;source=ROOT/'.goose/out/rc022-prep-20261114-01/source'
    probe.main('rc022_hmr_files.mts','Actual disk identities, coarse timestamp boundaries, captured/retained records, hard links and replacement inodes.',
        [Path(__file__).resolve(),ROOT/'dsh/cordis/hmr_files.py',source/'packages/boot/hmr/src/module-files.ts'],prepare)
