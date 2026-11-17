"""Current Loader-owned browser graph and immutable lazy resources."""
import json
import os
from urllib.parse import urlsplit

from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.host.client_modules.loader_registry import LoaderClientModuleRegistry
from dsh.host.client_modules.registry import (
    ClientPackageCompositionError,ABSENT,parse_dsh_client,client_export_of,graph_row,framed_hash,
    order_by_module_graph,partition_combo_records,short_hash,PARSER_PRELOAD_IDS,
    JAVASCRIPT_CONTENT_TYPE,JSON_CONTENT_TYPE,MissingClientBundleError,IMMUTABLE_CACHE,
    validate_source_map)
from dsh.host.client_modules.resources_current import build_combo


def current_graph_row(package,revision,meta):
    row=graph_row(package,revision,meta);row['url']=row['url'][1:];return row


def baseline_revision(baseline):
    return framed_hash('plugin-artifact',[stringify_json(baseline[key]).encode('utf-8') for key in ('mtimeMs','ctimeMs','size')])


class CurrentClientModuleRegistry(LoaderClientModuleRegistry):
    def __init__(self,ctx):
        import dsh
        self.release=dict(version=dsh.__version__)
        commit=os.environ.get('DSH_CLIENT_COMMIT_HASH')
        if commit is not None:self.release['commit']=commit
        super().__init__(ctx)

    def locate(self,name,base):
        if name.startswith('cordis:'):
            return None
        from dsh.cordis.loader import split_package_specifier
        path_like=name.startswith(('.', 'file:', '/', '\\')) or os.path.isabs(name)
        package,subpath=split_package_specifier(name)
        if not path_like and (not package or subpath is not None):return None
        packages=self.ctx.get('pluginPackages')
        if packages is not None and not path_like:
            selected=packages.packageOf(name,base)
            return None if selected is None else selected['manifestPath']
        return super().locate(name,base)

    def source(self,entry):
        name,base=entry.options['name'],getattr(entry.parent.tree.ctx,'baseUrl',None)
        if base is None:raise ValueError('client-modules: loader entry %s has no resolution base URL' % name)
        key=base+'\0'+name;manifest=self.locate(name,base)
        if manifest is None:return None
        with open(manifest,encoding='utf-8') as stream:package=json.load(stream)
        dsh=package.get('dsh')
        decl=parse_dsh_client(package['name'],dsh.get('client',ABSENT) if isinstance(dsh,dict) else ABSENT)
        if decl is None or decl['platform']!='web':return None
        target=client_export_of(package['name'],package.get('exports'))
        if target is None:raise ValueError('client-modules: %s declares dsh.client but exports no "./client" bundle' % package['name'])
        meta=dict(name=package['name'],client_path=os.path.normpath(os.path.join(os.path.dirname(manifest),target)),
            manifest_path=manifest,inject=decl.get('inject'),external=decl.get('external',[]),
            immediately=decl.get('immediately',False),source_key=key)
        return dict(key=key,name=name,base=base,meta=meta)

    def capture_artifact_baseline(self,path):
        info=os.stat(path)
        if os.name=='nt':
            from dsh.fs.win32_stat import node_stat
            info=node_stat(path,info)
        # Node derives milliseconds from integer seconds plus nanoseconds.
        def milliseconds(ns):return (ns//1000000000)*1000+(ns%1000000000)/1000000
        return dict(path=path,mtimeMs=milliseconds(info.st_mtime_ns),ctimeMs=milliseconds(info.st_ctime_ns),size=info.st_size)

    def _baseline(self,package,path):
        try:return self.capture_artifact_baseline(path)
        except FileNotFoundError as error:raise MissingClientBundleError(package,path,error) from error

    def initial_bundle_snapshot(self,package,path):
        baseline=self._baseline(package,path)
        try:
            with open(path,'rb') as stream:bundle=stream.read()
        except FileNotFoundError as error:raise MissingClientBundleError(package,path,error) from error
        return baseline,bundle,None

    def current_source_map(self,path):
        try:
            try:
                with open(path+'.map','rb') as stream:body=stream.read()
            except FileNotFoundError:return None
            return validate_source_map(path,body)
        except Exception as error:
            self._log_warn(error);return None

    def compose(self):
        entries=order_by_module_graph([record['entry'] for record in self._table.values()])
        bootstrap=[self._table[identity] for identity in PARSER_PRELOAD_IDS if identity in self._table]
        ids={record['id'] for record in bootstrap}
        application=[self._table[entry['id']] for entry in entries if entry['id'] not in ids]
        responses={};batches=[];batch_responses={}
        for phase,rows in [('bootstrap',bootstrap),('application',application)]:
            for records in partition_combo_records(rows):
                artifact=build_combo(records,self.current_source_map);revision=artifact['rev']
                batches.append(dict(phase=phase,url=artifact['url'][1:],rev=revision,entries=artifact['entries']))
                batch_responses[artifact['url']]=self._responses.get(artifact['url']) or dict(body=artifact['scriptBody'],contentType=JAVASCRIPT_CONTENT_TYPE)
                batch_responses[artifact['sourceMapUrl']]=self._responses.get(artifact['sourceMapUrl']) or dict(body=artifact['sourceMapBody'],contentType=JSON_CONTENT_TYPE)
        responses.update(batch_responses)
        for record in self._table.values():
            artifact=build_combo([record],self.current_source_map,record['entry']['rev'])
            responses.setdefault(artifact['url'],self._responses.get(artifact['url']) or dict(body=artifact['scriptBody'],contentType=JAVASCRIPT_CONTENT_TYPE))
            responses.setdefault(artifact['sourceMapUrl'],self._responses.get(artifact['sourceMapUrl']) or dict(body=artifact['sourceMapBody'],contentType=JSON_CONTENT_TYPE))
        self._previous_batch_responses=self._batch_responses;self._batch_responses=batch_responses;self._responses=responses
        self._composed=dict(rev=short_hash(stringify_json(dict(entries=entries,batches=batches)).encode('utf-8')),
            release=dict(self.release),entries=entries,batches=batches)
        return self._composed

    def reconcile(self,activation=False):
        self.queued=False
        if self.closed or not self.dirty:return
        errors=[];changed=False
        # Source freezes the Loader roster before doing synchronous resolution.
        entries={}
        try:
            for entry in self.loader.entries():entries.setdefault(entry.options['name'],[]).append(entry)
        except Exception as error:
            self.dirty.clear()
            if activation:raise ClientPackageCompositionError([error])
            self._log_warn(error);return
        for name in list(self.dirty):
            self.dirty.pop(name,None)
            try:
                next_sources={}
                for entry in entries.get(name,[]):
                    if entry.fiber is not None and not entry.disabled:
                        source=self.source(entry)
                        if source is not None:next_sources[source['key']]=source
                affected={}
                for key,source in list(self.sources.items()):
                    if source['name']==name:
                        affected[source['meta']['name']]=None
                        if key not in next_sources:del self.sources[key]
                for key,source in next_sources.items():
                    self.sources[key]=source;affected[source['meta']['name']]=None
                for package in affected:
                    try:
                        sources=[source for source in self.sources.values() if source['meta']['name']==package]
                        if len(sources)>1:
                            raise ValueError('client-modules: package %s resolves from multiple active Loader sources: %s; remove one entry' %
                                (package,', '.join('%s from %s' % (stringify_json(source['name']),source['base']) for source in sources)))
                        if not sources:
                            if package in self._table:
                                self._table.pop(package);self._pkg_meta.pop(package,None);changed=True
                            continue
                        meta=sources[0]['meta'];baseline=self._baseline(package,meta['client_path'])
                        entry=current_graph_row(package,baseline_revision(baseline),meta);current=self._table.get(package)
                        if current is not None and current['meta']==meta and current['entry']==entry:continue
                        baseline,bundle,source_map=self.initial_bundle_snapshot(package,meta['client_path'])
                        self._table[package]=dict(id=package,meta=meta,baseline=baseline,bundle=bundle,source_map=source_map,entry=entry)
                        self._pkg_meta[package]=meta;changed=True
                    except Exception as error:errors.append(error)
            except Exception as error:errors.append(error)
        if changed:
            try:self.compose();self.notify_graph_changed()
            except Exception as error:errors.append(error)
        if errors and activation:raise ClientPackageCompositionError(errors)
        for error in errors:self._log_warn(error)

    def rebuilt(self,package):
        record=self._table.get(package)
        if record is None:return None
        path=record['meta']['client_path'];baseline=self.capture_artifact_baseline(path);revision=baseline_revision(baseline)
        if revision==record['entry']['rev']:return revision
        with open(path,'rb') as stream:bundle=stream.read()
        record.update(baseline=baseline,entry=current_graph_row(package,revision,record['meta']),bundle=bundle)
        self.compose()
        for callback in list(self.rebuild_listeners):
            try:callback(package,revision)
            except Exception as error:self._log_warn(error)
        self.notify_graph_changed();return revision

    def client_path(self,package):
        record=self._table.get(package)
        return None if record is None else record['meta']['client_path']

    async def fetchBundle(self,request):
        method=request.get('method')
        if method not in ('GET','HEAD'):return dict(status=405,headers={},body=None)
        parsed=urlsplit(request['url'] if 'url' in request else self.resource_url(request))
        url=parsed.path+('?' + parsed.query if parsed.query else '')
        resource=self._responses.get(url) or self._previous_batch_responses.get(url)
        if resource is None:return dict(status=404,headers={},body=None)
        return dict(status=200,headers={'content-type':resource['contentType'],'cache-control':IMMUTABLE_CACHE},
            body=None if method=='HEAD' else await resource['body']())

    async def handle_plugin_request(self,request,response):
        resource=await self.fetchBundle(request)
        response.write_status(resource['status'])
        for key,value in resource['headers'].items():response.write_header(key,value)
        if resource['body'] is not None:response.write_body(resource['body'])
        await response.finish()


class CurrentClientModulesPlugin(Plugin):
    name='@deepseek-ai/dsh-client-modules'
    inject=['loader']

    def apply(self,ctx):
        self.registry=CurrentClientModuleRegistry(ctx)
        ctx.set_service('client_modules',self.registry);ctx.set_service('clientModules',self.registry)
        def web(child):
            child.effect(lambda:child.get('webServer').register('prefix','/plugins',self.registry.handle_plugin_request),'Client Modules Web carrier')
        ctx.inject(['webServer'],web)
        ctx.on('webserver/index-inject',lambda table,*_:table.extend(self.registry.boot_injections()))
