"""Static metadata collectors with controlled OS and actual Source query-wrapper ports."""
import asyncio
import base64
import copy
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    rows=[{}]
    for platform in ['darwin','linux','freebsd','aix']:
        rows.append(dict(sources=dict(platform=platform)))
    for root in [None,'','C:\\Windows','C:\\Windows\\..\\Windows']:
        rows.append(dict(sources=dict(SystemRoot=root)))
    for field in ['release','totalmem','cpus']:
        rows.append(dict(sources={field:{'throw':True}}))
    for value in [None,False,0,-1,1,1.5,9007199254740992]:rows.append(dict(sources=dict(totalmem=value)))
    for cpus in [[],[{}],[dict(model=None)],[dict(model=' ')],[dict(model='\ufeff Fixture CPU \u00a0')]]:
        rows.append(dict(sources=dict(cpus=cpus)))
    version=dict(major=10,minor=0,build='26100',revision=1)
    for field in version:
        for value in [None,-1,0,1.5,True,'1','',{},[],9007199254740992]:
            parsed=dict(version,**{field:value});rows.append(dict(version=dict(kind='value',stdout=json.dumps(parsed))))
        parsed=dict(version);parsed.pop(field);rows.append(dict(version=dict(kind='value',stdout=json.dumps(parsed))))
    for raw in ['', 'bad-json','\ufeff'+json.dumps(version), 'null','[]','{"major":NaN}']:
        rows.append(dict(version=dict(kind='value',stdout=raw)))
    for value in [None,{},[],[{}],[dict(cores=None,architecture=None)],[dict(cores=1,architecture=9),dict(cores=2,architecture=12)]]:
        rows.append(dict(cpu=dict(kind='value',stdout=json.dumps(value))))
    for field in ['cores','architecture']:
        for value in [None,False,0,-1,1,1.5,5,9,12,99,9007199254740992]:
            parsed=dict(cores=4,architecture=9,**{});parsed[field]=value
            rows.append(dict(cpu=dict(kind='value',stdout=json.dumps([parsed]))))
    for reason in ['query-failed','timeout','output-limit']:
        for field in ['version','cpu']:rows.append({field:dict(kind='missing',reason=reason)})
    for product,extra,build in [('14.1',None,'23A123'),('14.1.2',None,'23A123a'),('14',None,'23A123'),
        ('14.1 (a)',None,'23A123'),('14.1','(a)','23A123'),('14.1 (a)','(a)','23A123'),
        ('14.1 (a)','(b)','23A123'),('14.1','(A)','23A123'),('14.1',None,'bad'),('14.1.2.3',None,'23A123')]:
        raw='ProductVersion: '+product+'\nBuildVersion: '+build+('' if extra is None else '\nProductVersionExtra: '+extra)
        rows.append(dict(sources=dict(platform='darwin'),version=dict(kind='value',stdout=raw)))
    for cores in ['1','0','-1','1.5','9007199254740992','\u0661']:
        for arm in ['1','0','2']:
            rows.append(dict(sources=dict(platform='darwin'),cpu=dict(kind='value',stdout='hw.physicalcpu: '+cores+'\nhw.optional.arm64: '+arm)))
    return rows


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


def fixtures(entry):
    sources=dict(platform='win32',app_arch='x64',SystemRoot='C:\\Windows',release='10.0.26100',
        totalmem=17179869184,cpus=[dict(model=' Fixture CPU '),dict(model='Fixture CPU')]);sources.update(entry.get('sources',{}))
    version=dict(kind='value',stdout='ProductVersion: 14.1\nBuildVersion: 23A123') if sources['platform']=='darwin' else dict(
        kind='value',stdout=json.dumps(dict(major=10,minor=0,build='26100',revision=1)))
    cpu=dict(kind='value',stdout='hw.physicalcpu: 4\nhw.optional.arm64: 1') if sources['platform']=='darwin' else dict(
        kind='value',stdout=json.dumps([dict(cores=4,architecture=9)]))
    return sources,entry.get('version',version),entry.get('cpu',cpu)


async def observe():
    from dsh.client.analytics_environment_current import collectEnvironment
    from dsh.cordis.json_text import stringify_json
    rows=[]
    for entry in cases():
        selected,version,cpu=fixtures(entry);calls=[]
        def source(field):
            def get():
                value=selected[field]
                if isinstance(value,dict) and value.get('throw'):raise RuntimeError('synthetic source failure')
                return copy.deepcopy(value)
            return get
        sources=dict(selected)
        for field in ['platform','release','totalmem','cpus']:sources[field]=source(field)
        async def query(command,args,options):
            calls.append(dict(command=command,args=args,timeoutMillis=options['timeoutMillis'],maxOutputBytes=options['maxOutputBytes']))
            await asyncio.sleep(0)
            return copy.deepcopy(cpu if command=='/usr/sbin/sysctl' or '-EncodedCommand' in args and 'Get-CimInstance' in base64.b64decode(args[-1]).decode('utf-16-le') else version)
        value=await collectEnvironment(dict(timeoutMillis=123,maxOutputBytes=456),sources,query)
        rows.append(json.loads(stringify_json(dict(value=value,calls=calls))))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_analytics_environment.mts','Actual Source collector with controlled Node OS/execFile sources versus staged Native metadata/query ports: approved fields, fixed reasons and exact fixed command argv.',
        [Path(__file__).resolve(),ROOT/'dsh/client/analytics_environment_current.py'],prepare=prepare)
