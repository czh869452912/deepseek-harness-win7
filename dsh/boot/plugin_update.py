"""Current manager update planning and removal/install/restoration ownership."""
from dsh.boot.plugin_bundle_metadata import update_refusal
from dsh.boot.plugin_compatibility import evaluate_plugin_compatibility
from dsh.boot.plugin_git_connection import check_git_connection
from dsh.boot.plugin_install_spec import parse_install_spec, pinned_git_origin
from dsh.boot.plugin_registry_policy import UNSPECIFIED, VERSION_FIELDS, registry_plan, version_facts
from dsh.boot.profile_compatibility import read_profile_version_exemptions
from dsh.boot.runtime_resolution import _field
from dsh.boot.semver import parse
from dsh.core.cleanup import CleanupPromise
from dsh.typert.remote import Remote


class PluginUpdate:
    def _plan_git_update(self,name,origin,options):
        spec=options.get('spec',UNSPECIFIED)
        pinned=None if spec is UNSPECIFIED else pinned_git_origin(spec)
        if pinned is None:
            return dict(code='invalid-spec',diagnostic=name+' is installed from Git and updates only to a Git spec pinned to a full commit')
        if pinned!=origin:
            return dict(code='invalid-spec',diagnostic=spec+' is not in the repository directory '+name+' is installed from, '+origin)
        return dict(spec=spec,registry=self._registry_for(name,options.get('registry',UNSPECIFIED)),saveExact=False)

    async def _git_host_unreachable(self,spec):
        parsed=parse_install_spec(spec)
        if parsed['kind']!='git':return None
        options=dict(timeoutMs=self.github_connection_timeout_ms,outputBytes=self.output_bytes,signal=self.abort.signal)
        env=_field(_field(self.profile,'packageManager'),'env')
        if env is not None:options['env']=env
        failure=await self._owned_package_operation(check_git_connection(parsed,_field(self.profile,'dir'),options))
        self.abort.signal.throwIfAborted()
        if failure is None or failure['kind'] not in ('network','timeout'):return None
        return {key:value for key,value in failure.items() if key!='argv'}

    async def _check_registry_update(self,name,version,options):
        spec=name+'@'+version
        if 'spec' in options:
            return dict(code='invalid-spec',diagnostic=name+' is installed from a registry and updates only to '+spec)
        plan=registry_plan(self._registry_for(name,options.get('registry',UNSPECIFIED)),await self.registries())
        checked=await self._ask_registries(spec,VERSION_FIELDS,plan,dict(kind='registry',spec=spec,name=name))
        if checked['status']=='refused':return dict(code='operation-error',diagnostic=checked['reason'])
        facts=version_facts(checked['answer'],name,version)
        if not facts['bundle']:return dict(code='not-bundle')
        try:compatibility=evaluate_plugin_compatibility(facts['manifest'],read_profile_version_exemptions(_field(self.profile,'dir')))
        except Exception as error:return dict(code='operation-error',diagnostic=getattr(error,'message',str(error)))
        if compatibility is not None and not compatibility['exempted']:
            return dict(code='incompatible-version',incompatible=[{key:value for key,value in compatibility.items() if key!='exempted'}])
        return dict(spec=spec,registry=checked['registry'],saveExact=True)

    @Remote('updateBundle')
    def updateBundle(self,name,version,options=None):
        options=options or {};request_id=options.get('requestId')
        def announce(step):
            if request_id is not None:self.owner_context.emit('plugin-manager/update-state',dict(requestId=request_id,step=step))
        announce('checking')
        async def run():
            from dsh.boot.plugin_manager_current import management_error
            target=update_refusal(next((row for row in await self.listBundles() if row['name']==name),None),name)
            previous_version='' if isinstance(target,str) else target['installed']
            def answer(step,result,**extra):return dict(extra,**{'from':previous_version,'to':version,'step':step,'result':result})
            def refused(error):return answer('check',dict(changed=False,application='failed',stage='install',target=name,error=error))
            if isinstance(target,str):return refused(dict(code='invalid-spec',diagnostic=target))
            try:newer=parse(version)>parse(previous_version)
            except ValueError:newer=False
            if not newer:return refused(dict(code='invalid-spec',diagnostic=version+' is not a version newer than the installed '+previous_version))
            planned=(self._plan_git_update(name,target['origin'],options) if target['kind']=='git'
                else await self._check_registry_update(name,version,options))
            if 'code' in planned:return refused(planned)
            spec=planned['spec'];registry=planned['registry'];save_exact=planned['saveExact'];enabled=target['bundle']['enabled']
            async def settled(stage,specification,operation):
                try:return await operation
                except Exception as error:return dict(changed=False,application='failed',stage=stage,target=specification,error=management_error(error))
            def install_target():
                install_options=dict(saveExact=save_exact,enabled=enabled,expected=dict(name=name,version=version))
                if registry is not UNSPECIFIED:install_options['registry']=registry
                if request_id is not None:install_options['requestId']=request_id
                return settled('install',spec,self.installBundle(spec,install_options))
            if self.owner_context.get('hmr') is None:
                announce('installing');return answer('install',await install_target())
            unreachable=await self._git_host_unreachable(spec) if target['kind']=='git' else None
            if unreachable is not None:
                return answer('check',dict(changed=False,application='failed',stage='install',target=name,failedAt='spec-host',packageResult=unreachable,error=dict(code='operation-error',diagnostic=unreachable['output'])))
            previous_registry=self.installed_from.get(name,UNSPECIFIED)
            announce('removing');removal=await settled('remove',name,self.removeBundle(name))
            if removal['application'] in ('failed','cancelled'):return answer('remove',removal)
            announce('installing');result=await install_target()
            if result['application'] not in ('failed','cancelled'):return answer('install',result)
            announce('restoring')
            if result['stage']=='enable':await settled('remove',name,self.removeBundle(name))
            previous=target['source'] if target['kind']=='git' else name+'@'+previous_version
            restore_options=dict(saveExact=save_exact,enabled=enabled)
            if previous_registry is not UNSPECIFIED:restore_options['registry']=previous_registry
            # Restoration is owned by the update, without the cancelled request id.
            restore=await settled('install',previous,self.installBundle(previous,restore_options))
            return answer('install',result,restore=restore)
        return CleanupPromise(run())
