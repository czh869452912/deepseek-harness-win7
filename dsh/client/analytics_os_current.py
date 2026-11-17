"""Default static OS sources for the selected analytics metadata fields."""
import ctypes
import os
import platform
import sys


def _windows_release():
    class Version(ctypes.Structure):
        _fields_=[('size',ctypes.c_ulong),('major',ctypes.c_ulong),
            ('minor',ctypes.c_ulong),('build',ctypes.c_ulong),
            ('platform',ctypes.c_ulong),('service_pack',ctypes.c_wchar*128)]
    version=Version();version.size=ctypes.sizeof(version)
    rtl=ctypes.WinDLL('ntdll').RtlGetVersion
    rtl.argtypes=[ctypes.POINTER(Version)];rtl.restype=ctypes.c_long
    if rtl(ctypes.byref(version))<0:raise OSError('OS version unavailable')
    return '%d.%d.%d'%(version.major,version.minor,version.build)


def _totalmem():
    if os.name!='nt':return os.sysconf('SC_PHYS_PAGES')*os.sysconf('SC_PAGE_SIZE')
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
            (name,ctypes.c_ulonglong) for name in ['total','available','page_total',
                'page_available','virtual_total','virtual_available','extended_available']]
    memory=Memory();memory.length=ctypes.sizeof(memory)
    status=ctypes.WinDLL('kernel32',use_last_error=True).GlobalMemoryStatusEx
    status.argtypes=[ctypes.POINTER(Memory)];status.restype=ctypes.c_int
    if not status(ctypes.byref(memory)):raise ctypes.WinError(ctypes.get_last_error())
    return memory.total


def _cpus():
    if os.name=='nt':
        import winreg
        count=ctypes.WinDLL('kernel32',use_last_error=True).GetActiveProcessorCount
        count.argtypes=[ctypes.c_ushort];count.restype=ctypes.c_ulong
        logical=count(0xffff)  # ALL_PROCESSOR_GROUPS, available on Windows 7.
        if not logical:raise ctypes.WinError(ctypes.get_last_error())
        result=[]
        for index in range(logical):
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'HARDWARE\DESCRIPTION\System\CentralProcessor\%d'%index) as key:
                model=winreg.QueryValueEx(key,'ProcessorNameString')[0]
            result.append(dict(model=model))
        return result
    if sys.platform.startswith('linux'):
        with open('/proc/cpuinfo',encoding='utf-8') as stream:raw=stream.read()
        models=[line.split(':',1)[1].strip() for line in raw.splitlines() if line.startswith('model name') and ':' in line]
        if models:return [dict(model=model) for model in models]
    raise OSError('processor model unavailable')


def default_sources():
    machine=platform.machine().lower()
    arch='ia32' if sys.maxsize<=2147483647 else dict(amd64='x64',x86_64='x64',aarch64='arm64').get(machine,machine)
    return dict(platform=lambda:'win32' if os.name=='nt' else sys.platform,
        app_arch=arch,SystemRoot=os.environ.get('SystemRoot'),
        release=_windows_release if os.name=='nt' else platform.release,totalmem=_totalmem,cpus=_cpus)


async def collectEnvironment(options):
    from dsh.client.analytics_environment_current import collectEnvironment as collect
    from dsh.client.analytics_environment_query_current import queryEnvironment
    return await collect(options,default_sources(),queryEnvironment)
