"""Static analytics metadata collection over explicit OS and bounded-query ports."""
import asyncio
import base64
import json
import math
import ntpath
import re

from dsh.cordis.utils import _UNDEFINED, _js_number_value, js_to_string
from dsh.host.http_proxy_policy import JS_SPACE

VERSION_QUERY="""
$ErrorActionPreference = 'Stop'
$r = Get-Item -LiteralPath 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion'
@{ major = $r.GetValue('CurrentMajorVersionNumber'); minor = $r.GetValue('CurrentMinorVersionNumber'); build = $r.GetValue('CurrentBuildNumber'); revision = $r.GetValue('UBR') } | ConvertTo-Json -Compress
"""
CPU_QUERY="""
$ErrorActionPreference = 'Stop'
ConvertTo-Json -Compress -InputObject @(Get-CimInstance -ClassName Win32_Processor -Property NumberOfCores,Architecture | ForEach-Object { @{ cores = $_.NumberOfCores; architecture = $_.Architecture } })
"""
EXTRA_FIELDS=['os_version_full','os_build','os_arch','cpu_physical_core_count']
MAX_SAFE_INTEGER=9007199254740991


def _integer(value,minimum):
    if type(value) not in (int,float):return False
    number=_js_number_value(value)
    return math.isfinite(number) and minimum<=number<=MAX_SAFE_INTEGER and int(number)==number


def _invalid_constant(_value):raise ValueError('invalid JSON')


def _decode(stdout,kind):
    try:
        value=json.loads(stdout,parse_constant=_invalid_constant)
        if kind=='version':
            if not isinstance(value,dict) or any(key not in value for key in ['major','minor','build','revision']):return None
            if any(value[key] is not None and not _integer(value[key],0) for key in ['major','minor','revision']):return None
            if value['build'] is not None and (not isinstance(value['build'],str) or not re.fullmatch(r'[0-9]+',value['build'])):return None
        else:
            if not isinstance(value,list) or not value:return None
            for row in value:
                if not isinstance(row,dict) or 'cores' not in row or 'architecture' not in row:return None
                if row['cores'] is not None and not _integer(row['cores'],1):return None
                if row['architecture'] is not None and not _integer(row['architecture'],-MAX_SAFE_INTEGER):return None
        return value
    except (ValueError,TypeError,OverflowError):return None


def _lines(stdout):
    result={}
    for line in re.split(r'\r?\n',stdout.strip(JS_SPACE)):
        colon=line.find(':');result[line[:colon].strip(JS_SPACE)]=line[colon+1:].strip(JS_SPACE)
    return result


async def collectEnvironment(options,sources,query):
    host=sources['platform']()
    fields=dict(os_name='macos' if host=='darwin' else 'windows' if host=='win32' else host,
        app_arch=sources['app_arch'],missing_fields={})
    def missing(keys,reason):
        for key in keys:fields['missing_fields'][key]=reason
    def read(key,callback):
        try:value=callback()
        except Exception:missing([key],'unavailable');return
        if value is _UNDEFINED or value=='' or type(value) in (int,float) and not _integer(value,1):
            missing([key],'unavailable');return
        fields[key]=value
    read('os_version',lambda:host+' '+js_to_string(sources['release']()))
    read('memory_total_bytes',sources['totalmem'])
    try:processors=sources['cpus']()
    except Exception:processors=[]
    read('cpu_model',lambda:processors[0]['model'].strip(JS_SPACE) if processors else _UNDEFINED)
    read('cpu_logical_count',lambda:len(processors))
    if host=='win32':
        root=sources.get('SystemRoot')
        if root is None or root=='':missing(EXTRA_FIELDS,'unavailable');return fields
        command=ntpath.normpath(ntpath.join(root,'System32','WindowsPowerShell','v1.0','powershell.exe'))
        async def powershell(script):
            args=['-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode('ascii')]
            return await query(command,args,options)
        version,cpu=await asyncio.gather(powershell(VERSION_QUERY),powershell(CPU_QUERY))
        if version['kind']=='missing':missing(EXTRA_FIELDS[:2],version['reason'])
        else:
            parsed=_decode(version['stdout'],'version')
            if parsed is None:missing(EXTRA_FIELDS[:2],'invalid-value')
            else:
                if parsed['build'] is None:missing(['os_build'],'unavailable')
                else:fields['os_build']=parsed['build']
                if any(parsed[key] is None for key in ['major','minor','build','revision']):missing(['os_version_full'],'unavailable')
                else:fields['os_version_full']='.'.join(js_to_string(parsed[key]) for key in ['major','minor','build','revision'])
        if cpu['kind']=='missing':missing(EXTRA_FIELDS[2:],cpu['reason'])
        else:
            parsed=_decode(cpu['stdout'],'cpu')
            if parsed is None:missing(EXTRA_FIELDS[2:],'invalid-value')
            else:
                if all(row['cores'] is not None for row in parsed):read('cpu_physical_core_count',lambda:sum(row['cores'] for row in parsed))
                else:missing(['cpu_physical_core_count'],'unavailable')
                arch=parsed[0]['architecture'];architectures={0:'ia32',5:'arm',9:'x64',12:'arm64'}
                if arch not in architectures or not all(row['architecture']==arch for row in parsed):missing(['os_arch'],'unavailable')
                else:fields['os_arch']=architectures[arch]
    elif host=='darwin':
        version,cpu=await asyncio.gather(query('/usr/bin/sw_vers',[],options),
            query('/usr/sbin/sysctl',['-i','hw.physicalcpu','hw.optional.arm64'],options))
        if version['kind']=='missing':missing(EXTRA_FIELDS[:2],version['reason'])
        else:
            values=_lines(version['stdout']);product=values.get('ProductVersion');extra=values.get('ProductVersionExtra') or None
            match=re.fullmatch(r'([0-9]+(?:\.[0-9]+){1,2})(?: (\([a-z]\)))?',product) if product is not None else None
            if match and (extra is None or re.fullmatch(r'\([a-z]\)',extra)) and (match[2] is None or extra is None or match[2]==extra):
                suffix=match[2] or extra;fields['os_version_full']=product if suffix is None else match[1]+' '+suffix
            else:missing(['os_version_full'],'invalid-value')
            build=values.get('BuildVersion')
            if build is not None and re.fullmatch(r'[0-9]+[A-Za-z][0-9]+[a-z]?',build):fields['os_build']=build
            else:missing(['os_build'],'invalid-value')
        if cpu['kind']=='missing':missing(EXTRA_FIELDS[2:],cpu['reason'])
        else:
            values=_lines(cpu['stdout']);cores=values.get('hw.physicalcpu')
            if cores is not None and re.fullmatch(r'[0-9]+',cores) and _integer(int(cores),1):fields['cpu_physical_core_count']=int(cores)
            else:missing(['cpu_physical_core_count'],'invalid-value')
            arm=values.get('hw.optional.arm64')
            if arm=='1':fields['os_arch']='arm64'
            elif arm is None or arm=='0':fields['os_arch']='x64'
            else:missing(['os_arch'],'invalid-value')
    else:missing(EXTRA_FIELDS,'unsupported')
    return fields
