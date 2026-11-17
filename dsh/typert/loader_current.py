"""Resolve current generated Host artifacts from their canonical package owner."""
import os

from dsh.cordis.loader import module_search_dirs,split_package_specifier
from dsh.typert.loader import TypertLoader


class CurrentTypertLoader(TypertLoader):
    def package_manifest(self,ctx,name,base):
        package,subpath=split_package_specifier(name)
        if subpath or name.startswith(('.', '/', '\\', 'cordis:', 'file:')) or os.path.isabs(name):return True,None
        packages=ctx.get('pluginPackages')
        if packages is not None:
            try:selected=packages.packageOf(name,getattr(ctx,'baseUrl',base))
            except Exception:return True,None
            return True,None if selected is None else selected['manifestPath']
        loader=ctx.get('loader')
        for root in module_search_dirs(base,getattr(loader,'installation_module_roots',[])):
            candidate=os.path.join(root,package,'package.json')
            if os.path.isfile(candidate):return True,candidate
        return True,None
