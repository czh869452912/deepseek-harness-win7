"""Profile package service transactions; package executable remains application-owned."""
import asyncio
import json
import os
import re
import tempfile
import time

from dsh.boot.app_boot import load_overlay_patches
from dsh.boot.bundle_platform import assert_bundle_platform, UnsupportedBundlePlatformError, UNDECLARED
from dsh.boot.plugin_bundle_metadata import bundle_directory, bundle_manifest
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility, plugin_compatibility_warning
from dsh.boot.plugin_install_spec import parse_install_spec
from dsh.boot.plugin_package_run import run_package_process
from dsh.boot.plugin_package_view import _execute_package_query
from dsh.boot.profile import read_profile_manifest, resolve_profile_dir, bundle_patch_paths, compose_entries
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.runtime_resolution import _field
from dsh.cordis.utils import js_to_string, _js_own_enumerable_keys
from dsh.core.abort import AbortController
from dsh.util.atomic_write import write_file_atomic


def anchor_path_spec(argument, cwd):
    match=re.fullmatch(r'((?:file|link):)?(\.{1,2}(?:[/\\].*)?)',argument)
    return (match.group(1) or '')+os.path.abspath(os.path.join(cwd,match.group(2))) if match else argument


def _optional_file(path):
    try:
        with open(path,encoding='utf-8',errors='replace',newline='') as stream:return stream.read()
    except FileNotFoundError:return None


def _tree_alive(tree):
    pid=tree['pid']
    # Node's process.kill validates a signed 32-bit pid before consulting the
    # host. Do not let ctypes truncate an oversized stale record to another pid.
    if pid>2147483647:return False
    if os.name=='nt':
        from dsh.subprocess.windows_inspector import WindowsProcessInspector
        state=WindowsProcessInspector().state(pid)
        return state is not None and state['active']
    try:os.kill(-pid if tree['grouped'] else pid,0);return True
    except (OSError,OverflowError):return False


async def active_recorded_run(directory, alive=None, wait_ms=5000):
    path=os.path.join(directory,'.plugin-manager','run.json');text=_optional_file(path)
    if text is None:return None
    tree=None
    try:
        value=json.loads(text)
        if (isinstance(value,dict) and type(value.get('pid')) in (int,float) and 0<value['pid']<=9007199254740991
                and value['pid']==int(value['pid']) and type(value.get('grouped')) is bool):tree=dict(pid=int(value['pid']),grouped=value['grouped'])
    except ValueError:pass
    if tree is None:return 'dsh: '+path+' does not name a package run; delete it once no earlier package operation is still running in this profile\n'
    probe=alive or _tree_alive;deadline=time.monotonic()+wait_ms/1000
    while probe(tree):
        if time.monotonic()>=deadline:break
        await asyncio.sleep(.015)
    if probe(tree):
        return ('dsh: process '+str(tree['pid'])+', started by an earlier package operation whose own process ended, is still running in this profile; '
            'wait for it or stop it, then retry. If process '+str(tree['pid'])+' is not that package run, delete '+path+'.\n')
    try:os.unlink(path)
    except FileNotFoundError:pass
    return None


def _dependencies(manifest):
    result={}
    for key in ('devDependencies','dependencies','optionalDependencies'):result.update(manifest.get(key) or {})
    return {key:result[key] for key in _js_own_enumerable_keys(result)}


async def _save_manifest(directory,manifest):
    await write_file_atomic(os.path.join(directory,'package.json'),json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',mode=0o600)


def _components(manifest,directory,anchor):
    bundle=_field(_field(manifest,'dsh'),'bundle')
    if bundle is None:return []
    patches=[]
    for file in bundle_patch_paths(directory,bundle):patches.extend(load_overlay_patches('dsh',file))
    names=[]
    def visit(rows):
        for row in rows:
            if row.get('group') and isinstance(row.get('config'),list):visit(row['config'])
            name=row.get('name')
            if not isinstance(name,str) or name.startswith(('.','/')) or ':' in name:continue
            package='/'.join(name.split('/')[:2 if name.startswith('@') else 1])
            if package not in names:names.append(package)
    visit(compose_entries([[patch for patch in patches if 'insert' in patch]]))
    result=[]
    for name in names:
        try:package=bundle_directory(name,directory,anchor)
        except Exception:continue
        result.append(read_profile_manifest('dsh',package))
    return result


async def _reconcile(before,directory,anchor,on_output):
    after=read_profile_manifest('dsh',directory);dependencies=_js_own_enumerable_keys(after.get('dependencies') or {});before_deps=set(before.get('dependencies') or {})
    previous=_field(_field(after.get('dsh'),'profile'),'bundles',[]) or []
    bundles=[name for name in previous if (name not in before_deps and name not in dependencies)
        or (name in dependencies and bundle_manifest(name,directory,anchor) is not None)]
    unsupported=[]
    for name in dependencies:
        if name in before_deps:continue
        metadata=bundle_manifest(name,directory,anchor)
        bundle=_field(_field(metadata,'dsh'),'bundle')
        if bundle is None:
            if on_output:on_output('dsh: warning: '+name+' declares no dsh.bundle — installed as a plain dependency, not a profile layer\n','stderr')
            continue
        try:assert_bundle_platform(bundle.get('platforms',UNDECLARED))
        except UnsupportedBundlePlatformError as error:unsupported.append(name+': '+str(error));continue
        for file in bundle_patch_paths(bundle_directory(name,directory,anchor),bundle):load_overlay_patches('dsh',file)
        if name not in bundles:bundles.append(name)
    if unsupported:return unsupported
    if previous!=bundles:
        after.setdefault('dsh',{}).setdefault('profile',{})['bundles']=bundles
        await _save_manifest(directory,after)
    return []


async def _named_manifest(directory,spec,options,flags):
    parsed=parse_install_spec(spec)
    if parsed['kind']=='path':
        text=_optional_file(os.path.join(parsed['path'],'package.json'))
        return json.loads(text) if text is not None else None
    if parsed['kind']!='registry':return None
    argv=[options.get('command','pnpm')]+list(options.get('args') or [])+['view',parsed['spec'],'name','version','engines','peerDependencies','--json']+flags+['--config.fetch-retries=0']
    viewed=await _execute_package_query(directory,argv,dict(options,timeoutMs=options.get('lookupTimeoutMs',20000)))
    if viewed['exitCode']!=0:return None
    value=json.loads(viewed['stdout'])
    return (value[-1] if value else None) if isinstance(value,list) else value


async def run_profile_pnpm(context,args,options):
    """Run one service operation while the caller holds package.json's lock."""
    if options.get('execution','service')!='service':raise ValueError('this package process engine captures service runs')
    directory=context.get('dir') or resolve_profile_dir(context['profile'],context.get('home'))
    active=await active_recorded_run(directory)
    before=read_profile_manifest('dsh',directory) if active is None else None
    before_deps=_dependencies(before) if before is not None else {}
    installed_before={name:_optional_file(os.path.join(directory,'node_modules',name,'package.json')) for name in before_deps}
    result=None;tail=bytearray();incompatible=[];warnings=[];unmet=None
    def fresh_result():
        root=os.path.join(directory,'.plugin-manager','logs');os.makedirs(root,mode=0o700,exist_ok=True)
        path=os.path.join(tempfile.mkdtemp(prefix='operation-',dir=root),'pnpm.log')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(descriptor)
        return dict(exitCode=1,output='',truncated=False,logPath=path)
    def emit(text,capture=True):
        data=text.encode('utf-8')
        with open(result['logPath'],'ab') as stream:stream.write(data)
        if options.get('onOutput'):options['onOutput'](text,'stderr')
        if capture:
            tail.extend(data)
            if len(tail)>options['outputBytes']:
                result['truncated']=True;del tail[:len(tail)-options['outputBytes']]
            result['output']=tail.decode('utf-8',errors='replace')
    if active is not None:
        result=fresh_result();emit(active);return result
    saved={name:_optional_file(os.path.join(directory,name)) for name in ('package.json','pnpm-lock.yaml')}
    command=next((index for index,arg in enumerate(args) if not arg.startswith('-')),None)
    specs=[] if command is None or args[command] not in ('add','install','i') else [arg for arg in args[command+1:] if not arg.startswith('-')]
    preflight=[];flags=[arg for arg in args if arg.startswith('--registry=')]
    for spec in specs:
        try:
            manifest=await _named_manifest(directory,anchor_path_spec(spec,context['cwd']),options,flags)
            if manifest is None:continue
            issue=evaluate_plugin_compatibility(manifest,read_profile_version_exemptions(directory))
            if issue is not None and not issue['exempted']:
                preflight.append(plugin_compatibility_warning(issue));incompatible.append({key:value for key,value in issue.items() if key!='exempted'})
        except Exception:continue
    if preflight:
        result=fresh_result();emit('\ndsh: installation rejected: '+'\n'.join(preflight)+'\ndsh: nothing was installed.\n')
        result['incompatible']=incompatible;return result
    argv=[options.get('command','pnpm')]+list(options.get('args') or [])+[anchor_path_spec(arg,context['cwd']) for arg in args]
    result=await run_package_process(directory,argv,options)
    if result['exitCode']!=0 or result.get('timedOut'):return result
    with open(result['logPath'],'rb') as stream:
        stream.seek(0,os.SEEK_END);size=stream.tell();stream.seek(max(0,size-options['outputBytes']))
        tail.extend(stream.read(options['outputBytes']))
    after=read_profile_manifest('dsh',directory);expected=options.get('expected');seen=False
    def fail(code,warning):
        nonlocal unmet
        if unmet!='unexpected-package':unmet=code
        warnings.append(warning)
    for name,spec in _dependencies(after).items():
        package=os.path.join(directory,'node_modules',name);installed=_optional_file(os.path.join(package,'package.json'))
        if installed is None:continue
        untouched=before_deps.get(name)==spec and installed_before.get(name)==installed
        found=[];issues=[]
        try:
            manifest=read_profile_manifest('dsh',package);installed_as=name+'@'+(js_to_string(manifest['version']) if 'version' in manifest else 'undefined')
            wanted=expected['name']+'@'+expected['version'] if expected is not None else None
            if expected is not None and name==expected['name']:
                seen=True
                if installed_as!=wanted:fail('unexpected-package',installed_as+' is installed where '+wanted+' was expected')
                elif 'bundle' not in (manifest.get('dsh') or {}):fail('not-bundle',installed_as+' declares no bundle')
                else:
                    for file in bundle_patch_paths(package,manifest['dsh']['bundle']):load_overlay_patches('dsh',file)
            elif wanted is not None and not untouched:fail('unexpected-package',installed_as+' is installed where '+wanted+' was expected')
            for candidate in [manifest]+_components(manifest,package,context['installAnchor']):
                issue=evaluate_plugin_compatibility(candidate,read_profile_version_exemptions(directory))
                if issue is not None and not issue['exempted']:
                    found.append(plugin_compatibility_warning(issue));issues.append({key:value for key,value in issue.items() if key!='exempted'})
        except Exception as error:found.append('Cannot validate installed package '+name+': '+getattr(error,'name','Error')+': '+str(error))
        if not found:continue
        if not untouched:warnings.extend(found);incompatible.extend(issues)
        else:emit('\ndsh: warning: '+'\n'.join(found)+'\ndsh: it stays installed but profile startup denies it until you grant an exemption for those exact versions.\n',False)
    if expected is not None and not seen:fail('unexpected-package',expected['name']+'@'+expected['version']+' is not installed')
    if warnings:
        for name,text in saved.items():
            path=os.path.join(directory,name)
            if text is None:
                try:os.unlink(path)
                except FileNotFoundError:pass
            else:await write_file_atomic(path,text,mode=0o600)
        repair=['install','--frozen-lockfile' if saved['pnpm-lock.yaml'] is not None else '--config.lockfile=false']
        control=AbortController();timer=asyncio.get_running_loop().call_later(options['idleTimeoutMs']/1000,control.abort) if options.get('idleTimeoutMs') is not None else None
        try:repaired=await run_package_process(directory,[options.get('command','pnpm')]+list(options.get('args') or [])+repair,
            dict(outputBytes=options['outputBytes'],env=options.get('env'),signal=control.signal))
        finally:
            if timer is not None:timer.cancel()
        restoration='restored package.json, pnpm-lock.yaml, and node_modules' if repaired['exitCode']==0 else "restored package.json and pnpm-lock.yaml, but node_modules could not be reinstalled; run 'dsh plugin install'"
        result['exitCode']=1
        emit('\ndsh: installation rejected: '+'\n'.join(warnings)+'\ndsh: '+restoration+'.\n')
    elif options.get('activateNewBundles') is not False:
        unsupported=await _reconcile(before,directory,context['installAnchor'],options.get('onOutput'))
        if unsupported:
            result['exitCode']=1
            emit('\ndsh: bundle activation rejected: '+'\n'.join(unsupported)+"\ndsh: installed dependencies remain; bundle selection is unchanged. Use a supported Host or remove the unwanted dependencies with 'dsh plugin remove <package>'.\n")
    if incompatible:result['incompatible']=incompatible
    if unmet is not None:result['unmet']=unmet
    return result
