"""Pair historical child prerequisite reads through real plaintext/zstd files."""
import argparse
import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = '38a6a5c965aa99ab525161efb7cc5cf1fe62fced'


def cases():
    rows = []
    descriptor = dict(type='subagent/descriptor', seq=0, time=2,
                      data=dict(version=3, provider='spawn', mode='continuable', label='child label'))
    variants = [dict(events=[]), dict(events=[descriptor], mutate=True),
                dict(events=[descriptor, dict(descriptor, seq=1)]),
                dict(events=[dict(descriptor, data={'version': 99})]),
                dict(events=[], bodyText='{broken\n'),
                dict(events=[], bodyText='{broken\n'+json.dumps(dict(type='turn/end',seq=1,time=2,data={'turn':1,'reason':{'kind':'completed'}}))+'\n'),
                dict(events=[], headerText='{broken\n'), dict(events=[], indexHeader={'createdAt': 3}),
                dict(events=[], indexHeader={'agentPreset':'changed'}), dict(events=[], header={'parentSession':'other'}),
                dict(events=[], filename='session.v03.jsonl'), dict(events=[], abort=True)]
    for version in (1, 2, 3):
        value = dict(version=version, provider='spawn', label='')
        if version != 1:
            value['mode'] = 'continuable'
        for changes in ({}, {'agentModel':''}, {'toolFilter':{'allow':['']}}, {'label':False},
                        {'agentReasoningEffort':''}, {'label':'child', 'agentProvider':'only'}):
            variants.append(dict(events=[dict(descriptor,data=dict(value,**changes))]))
    for compression in ('none', 'zstd'):
        for version in (0, 1, 2, 3):
            for variant in variants:
                value = dict(compression=compression, case='facts-%s' % len(rows), **variant)
                value['header'] = dict(variant.get('header', {}), version=version)
                rows.append(value)
    return rows


async def native(rows, workspace):
    from dsh.core.abort import AbortController
    from dsh.session.catalog_migration import prepareCatalogFacts
    from dsh.session.jsonl_current import generationLogFilename
    from dsh.session.jsonl_zstd import compress_frame
    results = []
    def error_value(error):
        return dict(name=getattr(error, 'name', 'TypeError' if isinstance(error, TypeError) else 'Error'), message=str(error))
    for row in rows:
        root = workspace/row['case']; root.mkdir(parents=True)
        header = dict(version=3,id='child',createdAt=2,isSeeded=False,delegationDepth=1,origin='subagent',parentSession='parent')
        header.update(row['header']); physical = dict(type='session', **header)
        if header['version'] < 2:
            del physical['isSeeded']
            if header['isSeeded']:
                physical['seedLength'] = 0
        path = root/row.get('filename', generationLogFilename(header['version'], row['compression']))
        first = row.get('headerText', json.dumps(physical)+'\n').encode('utf-8')
        body = row.get('bodyText', ''.join(json.dumps(event)+'\n' for event in row['events'])).encode('utf-8')
        original = first+body if row['compression']=='none' else compress_frame(first)+(compress_frame(body) if body else b'')
        path.write_bytes(original)
        controller=AbortController()
        if row.get('abort'):
            controller.abort(RuntimeError('cancelled prerequisite'))
        result = dict(case=row['case'])
        try:
            prepared = await prepareCatalogFacts('parent', [dict(path=str(path),header=dict(header,**row.get('indexHeader',{})))], row['compression'], controller.signal)
            result.update(facts=prepared.facts,failures=[dict(path=item['path'],error=error_value(item['error'])) for item in prepared.failures],unchanged=original==path.read_bytes())
            await prepared.validate();result['stable']=True
            if row.get('mutate'):
                path.write_bytes(original+b'changed')
                try:
                    await prepared.validate();result['changed']=False
                except Exception as error:
                    result['changed']=error_value(error)
        except Exception as error:
            result['error']=error_value(error)
        # Keep file identity observations semantic across independent fixtures.
        results.append(json.loads(json.dumps(result).replace(json.dumps(str(root))[1:-1], '<fixture>')))
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--node',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();output=args.output.resolve()
    output.relative_to(ROOT/'.goose/out');output.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],encoding='utf-8').strip()==TARGET
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],encoding='utf-8').strip()
    rows=cases();(output/'cases.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    command=[str(args.node.resolve()),str(source/'node_modules/tsx/dist/cli.mjs'),'--tsconfig',str(source/'tsconfig.base.json'),str(ROOT/'scripts/oracles/rc022_catalog_facts.mts'),str(source),str(output/'cases.json'),str(output/'source-workspace')]
    report=dict(target_upstream=TARGET,scope='V0-V3 real-file prerequisite collection only; V4 child reads and parent publication await installed Session/storage integration.',command=command)
    start=time.monotonic()
    try:
        result=subprocess.run(command,capture_output=True,timeout=120)
        (output/'source.json').write_bytes(result.stdout);(output/'source.stderr').write_bytes(result.stderr)
        report['source_exit_code']=result.returncode
        if result.returncode:raise RuntimeError('Source observer failed')
        observed=json.loads(result.stdout);local=asyncio.run(native(rows,output/'native-workspace'))
        (output/'native.json').write_text(json.dumps(local,ensure_ascii=False),encoding='utf-8')
        from scripts.session_format_oracle import json_equal
        differences=[dict(case=row['case'],source=a,native=b) for row,a,b in zip(rows,observed,local) if not json_equal(a,b)]
        assert len(observed)==len(local)==len(rows)
        report.update(cases=len(rows),matched=len(rows)-len(differences),differences=differences)
        assert not differences,'Source/native differences'
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',error=str(error));raise
    finally:
        report['seconds']=time.monotonic()-start
        paths=[source/'packages/session/session-persistence-jsonl/src/catalog-migration.ts',source/'packages/session/session-persistence-jsonl/src/generation.ts',ROOT/'dsh/session/catalog_migration.py',ROOT/'dsh/session/generation.py',ROOT/'scripts/oracles/rc022_catalog_facts.mts',Path(__file__).resolve(),output/'cases.json']
        for package in ('session-format', 'session-format-v0-to-v1', 'session-format-v1-to-v2',
                        'session-format-v2-to-v3', 'session-format-v3-to-v4', 'session-format-catalog'):
            paths.extend((source/'packages/session'/package/'src').glob('*.ts'))
        for package in ('format', 'format_v0_to_v1', 'format_v1_to_v2', 'format_v2_to_v3', 'format_v3_to_v4', 'format_catalog'):
            paths.extend((ROOT/'dsh/session'/package).glob('*.py'))
        paths.append(ROOT/'dsh/session/format_v0_to_v1/dispositions.json')
        report['inputs']={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if report.get('status')=='passed':
            removed=[]
            for name in ('source-workspace','native-workspace'):
                path=output/name
                path.resolve().relative_to(output)
                for child in path.rglob('*'):
                    if getattr(child.lstat(),'st_file_attributes',0)&1024:raise ValueError('Unexpected reparse '+str(child))
                size=sum(child.stat().st_size for child in path.rglob('*') if child.is_file())
                shutil.rmtree(str(path));removed.append(dict(path=name,bytes=size))
            (output/'cleanup.json').write_text(json.dumps(dict(owner='rc022-catalog-facts',removed=removed),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],matched=report['matched'])))


if __name__=='__main__':
    main()
