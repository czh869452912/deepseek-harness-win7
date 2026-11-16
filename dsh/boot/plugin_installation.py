"""Current package installation/removal Remote orchestration."""
import asyncio
import os
import sys
import uuid
from types import SimpleNamespace

from dsh.boot.plugin_build_approval import approve_builds, record_pending_builds
from dsh.boot.plugin_bundle_metadata import parsed_for_registry, bundle_selection
from dsh.boot.plugin_git_connection import check_github_connection, choose_git_transport, ssh_git_spec
from dsh.boot.plugin_install_spec import dependency_spec, classify_install_failure, JS_SPACE
from dsh.boot.plugin_package_operations import run_profile_pnpm
from dsh.boot.plugin_package_view import registry_arguments
from dsh.boot.plugin_registry_policy import UNSPECIFIED, registry_plan, attribute_failure
from dsh.boot.profile import read_profile_manifest
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.runtime_resolution import _field
from dsh.core.abort import AbortController
from dsh.core.cleanup import CleanupPromise
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.typert.remote import Remote
from dsh.util.atomic_write import write_file_atomic


def _failure(code, incompatible=None):
    from dsh.boot.plugin_manager_current import ManagementFailure
    return ManagementFailure(code,incompatible)


def _cancelled():
    from dsh.boot.plugin_manager_current import InstallCancelledError
    return InstallCancelledError()


def _linked(*signals):
    controller=AbortController();detach=[]
    for signal in signals:
        if signal is not None:detach.append(signal.add_listener('abort',controller.abort))
    def close():
        for disposer in detach:disposer()
    return controller.signal,close


def spec_package_name(spec,dependencies,profile_dir):
    parsed=parsed_for_registry(spec)
    if parsed['kind']=='registry':return parsed['name']
    if parsed['kind']=='path':
        try:return read_profile_manifest('dsh',parsed['path']).get('name')
        except Exception:return None
    alternative='file:'+parsed['path'] if parsed['kind']=='tarball' and 'path' in parsed else ssh_git_spec(parsed)
    specs=[spec] if alternative is None else [spec,alternative]
    return next((name for name in _js_own_enumerable_keys(dependencies) if dependency_spec(name,dependencies[name],profile_dir) in specs),None)


class PluginInstallation:
    async def _owned_package_operation(self,operation):
        task=asyncio.ensure_future(operation);self.package_operations.add(task)
        def settled(done):
            self.package_operations.discard(done)
            if not done.cancelled():done.exception()
        task.add_done_callback(settled)
        return await asyncio.shield(task)

    async def _run_pnpm(self,args,signal=None,request_id=None,expected=None,on_commit=None):
        argv=['pnpm']+list(args);job_id=str(uuid.uuid4());cwd=_field(self.profile,'dir')
        identity={} if request_id is None else dict(requestId=request_id)
        def emit(stream,text,**extra):self.owner_context.emit('plugin-manager/install-log',dict(identity,jobId=job_id,argv=argv,cwd=cwd,stream=stream,text=text,**extra))
        combined,detach=_linked(self.abort.signal,signal)
        options=dict(self._package_options(),execution='service',signal=combined,outputBytes=self.output_bytes,
            activateNewBundles=False,idleTimeoutMs=self.idle_timeout_ms,lookupTimeoutMs=self.inspect_timeout_ms,
            onOutput=lambda text,stream:emit(stream,text))
        if expected is not None:options['expected']=expected
        if on_commit is not None:options['onCommit']=on_commit
        context={key:_field(self.profile,key) for key in ('dir','cwd','home','installAnchor')};context['profile']=_field(self.profile,'name')
        try:
            backend=self.owner_context.get('profilePackages') if _field(self.profile,'packageManager') is None else None
            operation=run_profile_pnpm(context,args,options) if backend is None else backend.run(context,args,options)
            result=await self._owned_package_operation(operation)
            emit('stdout','',exitCode=None if signal is not None and signal.aborted else result['exitCode'])
            if result['exitCode']==0 and not result.get('timedOut'):return result
            return dict(result,kind=classify_install_failure(dict(log=result['output'],timedOut=result.get('timedOut'))))
        except Exception as error:
            emit('stderr',getattr(error,'message',str(error)),exitCode=None)
            raise
        finally:detach()

    def _restored_files(self):
        result={}
        for name in ('package.json','pnpm-lock.yaml'):
            path=os.path.join(_field(self.profile,'dir'),name)
            try:
                with open(path,encoding='utf-8',errors='replace',newline='') as stream:result[path]=stream.read()
            except FileNotFoundError:result[path]=None
        return result

    async def _restore_files(self,files):
        for path,content in files.items():
            if content is None:
                try:os.unlink(path)
                except FileNotFoundError:pass
            else:await write_file_atomic(path,content,mode=0o600)

    @Remote('installBundle')
    def installBundle(self,spec,options=None):
        options=options or {};request_id=options.get('requestId')
        control=SimpleNamespace(abort=AbortController(),phase='installing',result=None)
        if request_id is not None:self.installs[request_id]=control
        def stopped():return control.abort.signal.aborted or self.abort.signal.aborted
        def announce(phase,attempt=None):
            if request_id is not None:
                self.owner_context.emit('plugin-manager/install-state',dict(requestId=request_id,phase=phase,**({} if attempt is None else dict(attempt=attempt))))
        async def operation(result):
            if spec.strip(JS_SPACE)=='' or spec.startswith('-'):raise _failure('invalid-spec')
            if stopped():raise _cancelled()
            directory=_field(self.profile,'dir');before=read_profile_manifest('dsh',directory).get('dependencies') or {}
            known=spec_package_name(spec,before,directory)
            if self.owner_context.get('hmr') is not None and known is not None and known in before:raise _failure('already-installed')
            if 'approvedBuilds' in options:
                await approve_builds(directory,options['approvedBuilds']);result['approvedBuilds']=options['approvedBuilds']
            files=self._restored_files();combined,detach=_linked(self.abort.signal,control.abort.signal)
            try:
                result['registries']=[];parsed=parsed_for_registry(spec)
                env=_field(_field(self.profile,'packageManager'),'env')
                check_options=dict(timeoutMs=self.github_connection_timeout_ms,outputBytes=self.output_bytes,signal=combined)
                if env is not None:check_options['env']=env
                connection=await self._owned_package_operation(check_github_connection(parsed,directory,check_options))
                if stopped():raise _cancelled()
                if connection is not None and connection['kind'] in ('network','timeout'):
                    package_result={key:value for key,value in connection.items() if key!='argv'}
                    result.update(packageResult=package_result,failedAt='spec-host')
                    if request_id is not None:
                        self.owner_context.emit('plugin-manager/install-log',dict(requestId=request_id,jobId=str(uuid.uuid4()),argv=connection['argv'],cwd=directory,stream='stderr',text=connection['output'],exitCode=None if connection.get('timedOut') else connection['exitCode']))
                    raise RuntimeError(connection['output'])
                install_spec=await self._owned_package_operation(choose_git_transport(parsed,directory,dict(check_options,timeoutMs=self.git_transport_timeout_ms)))
                if stopped():raise _cancelled()
                plan=registry_plan(options.get('registry',UNSPECIFIED),await self.registries());run=None;used=None
                for index,registry in enumerate(plan):
                    if index>0:await self._restore_files(files)
                    if stopped():raise _cancelled()
                    result['registries'].append(registry);used=registry
                    announce('installing',dict(registry=registry,index=index+1,total=len(plan)))
                    def committing():
                        control.phase='applying';announce('applying')
                    run=await self._run_pnpm(['add',install_spec]+(['--save-exact'] if options.get('saveExact') is True else [])+registry_arguments(registry),control.abort.signal,request_id,options.get('expected'),committing)
                    result['packageResult']=run
                    if stopped() and not run.get('nativeCommitted'):raise _cancelled()
                    if 'incompatible' in run:raise _failure('incompatible-version',run['incompatible'])
                    if 'unmet' in run:raise _failure(run['unmet'])
                    if run['exitCode']==0 and run.get('timedOut') is not True:break
                    if 'kind' not in run:break
                    result.pop('failedAt',None)
                    if run.get('timedOut') is True:break
                    failed_at=attribute_failure(run['kind'],run['output'],parsed_for_registry(install_spec))
                    if failed_at!='other':result['failedAt']=failed_at
                    if failed_at!='registry' or index==len(plan)-1:break
                if run is None:raise RuntimeError('no registry was asked')
                succeeded=run['exitCode']==0 and run.get('timedOut') is not True
                if succeeded:result.pop('failedAt',None)
                if not succeeded:
                    try:result['pendingBuilds']=await record_pending_builds(directory,run['output'])
                    except Exception:sys.stderr.write('dsh plugin-manager: Could not read pending build approvals after pnpm failed\n')
                    raise RuntimeError(run['output'])
                after=read_profile_manifest('dsh',directory).get('dependencies') or {}
                installed=[name for name in _js_own_enumerable_keys(after) if before.get(name)!=after[name]]
                if not installed:
                    local=spec_package_name(spec,after,directory)
                    if local is not None and local in after:installed.append(local)
                if len(installed)!=1:raise _failure('ambiguous-install')
                name=installed[0];manifest=self._bundle_manifest(name)
                if manifest is None:raise _failure('not-bundle')
                self._assert_compatibility(manifest,read_profile_version_exemptions(directory))
                self._bundle_patches(name,manifest)
                self.installed_from[name]=used
            except Exception:
                await self._restore_files(files)
                raise
            finally:detach()
            if control.phase!='applying':
                control.phase='applying';announce('applying')
            result.update(bundle=name,target=name,stage='enable')
            if 'version' in manifest:result['version']=manifest['version']
            async def apply():
                if options.get('enabled') is not False:await self._select_bundle(name,True)
                if name in before and self.owner_context.get('hmr') is None:return
                selected=name in bundle_selection(read_profile_manifest('dsh',directory))
                result.update(await self._publish_and_reload([row['id'] for row in self._bundle_rows(name)] if selected else []))
            return await self._configure(apply)
        async def run():
            try:return await self._change(operation,dict(stage='install',target=spec,enabled=options.get('enabled') is not False),'install')
            finally:
                if request_id is not None:self.installs.pop(request_id,None)
        control.result=CleanupPromise(run())
        return control.result

    @Remote('waitForInstall')
    def waitForInstall(self,request_id):
        control=self.installs.get(request_id)
        async def wait():return None if control is None else await control.result
        return CleanupPromise(wait())

    @Remote('cancelInstall')
    def cancelInstall(self,request_id):
        control=self.installs.get(request_id)
        async def answer(status):return dict(status=status)
        if control is None:return CleanupPromise(answer('not-running'))
        if control.phase=='applying':return CleanupPromise(answer('too-late'))
        self.owner_context.emit('plugin-manager/install-state',dict(requestId=request_id,phase='cancelling'))
        control.abort.abort()
        async def wait():
            try:await control.result
            except Exception:pass
            return dict(status='cancelled')
        return CleanupPromise(wait())

    @Remote('removeBundle')
    def removeBundle(self,name):
        async def operation(result):
            async def prepare():
                bundle=next((row for row in await self.listBundles() if row['name']==name),None)
                if bundle is None or not bundle['removable']:raise _failure('not-removable')
                contributions=self._bundle_rows(name) if 'error' not in bundle else []
                entries=list(self.ctx.loader.entries())
                if self.owner_context.get('hmr') is None and (name in _field(self.profile,'startedBundles') or
                    any(entry.options.get('id')==row.get('id') and entry.fiber is not None for row in contributions for entry in entries)):raise _failure('stop-profile')
                if bundle['enabled']:
                    await self._select_bundle(name,False);result.update(await self._reload())
                if any(_field(entry.fiber,'uid') is not None and any(row.get('id')==entry.options.get('id') and row.get('name')==entry.options.get('name') for row in contributions) for entry in self.ctx.loader.entries()):raise _failure('bundle-in-use')
                return bundle['installed']
            installed=await self._configure(prepare)
            if not installed:return
            registry=self.installed_from.get(name,self.registry)
            result['packageResult']=await self._run_pnpm(['remove',name]+(['--config.registry='+registry] if isinstance(registry,str) else []))
            if result['packageResult']['exitCode']!=0 or result['packageResult'].get('timedOut') is True:raise RuntimeError(result['packageResult']['output'])
            self.installed_from.pop(name,None)
            async def apply():result.update(await self._publish_and_reload())
            await self._configure(apply)
        return CleanupPromise(self._change(operation,dict(stage='remove',target=name),'remove'))
