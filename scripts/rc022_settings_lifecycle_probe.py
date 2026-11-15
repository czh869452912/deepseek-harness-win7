"""Real profile-backed ConfigEditor/Settings/Loader integration."""
import asyncio
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from dsh.boot.app_boot import boot
    from dsh.boot.profile_context import read_profile_patches
    from dsh.boot.config_editor import ConfigEditor
    from dsh.cordis.schema import Schema as z
    from dsh.settings.forms import SettingsForms
    from dsh.boot.profile_boot import create_app_ready
    from dsh.cordis.hmr import ConfigWatcherService
    from dsh.cordis.timer import TimerService
    root=(workspace or WORKSPACE)/'native';directory=root/'profiles/test';bundle=directory/'node_modules/test-bundle';bundle.mkdir(parents=True)
    def write(path,value):path.write_text(json.dumps(value),encoding='utf-8')
    write(root/'package.json',dict(name='test-installation'))
    write(directory/'package.json',dict(name='test-profile',dsh=dict(profile=dict(bundles=['test-bundle']))))
    write(bundle/'package.json',dict(name='test-bundle',version='1.0.0',dsh=dict(bundle=dict(patch='cordis.patch.yml'))))
    write(bundle/'cordis.patch.yml',[dict(insert=[dict(id='config-editor',name='cordis:editor'),dict(id='settings',name='cordis:settings'),dict(id='probe',name='cordis:probe',config=dict(ordinary='fixed',count=2,token='private'))])])
    write(directory/'cordis.yml',[])
    (directory/'cordis.patch.yml').write_text('# profile\n- id: probe # identity\n  name: cordis:probe # module\n  # configuration\n  config:\n    ordinary: fixed\n    count: 2\n    token: private\n# tail\n',encoding='utf-8')
    profile=dict(name='test',startedBundles=['test-bundle'],dir=str(directory),patchPath=str(directory/'cordis.patch.yml'),installAnchor=str(root/'package.json'),cwd=str(root),home=str(root),overlays=[],telemetryDisabledEnv=None)
    def plugin(ctx,config):
        if config['ordinary']=='rejected':raise RuntimeError('fixture rejects ordinary value')
    plugin.Config=z.object(dict(ordinary=z.string().required(),count=z.number().min(1).default(2).volatile(),token=z.string().role('secret').volatile()))
    def prepare(ctx):
        ctx.set_service('profileContext',profile);ctx.loader.builtins.update(editor=ConfigEditor,settings=SettingsForms,probe=plugin)
        ready=create_app_ready();ctx.set_service('appReady',ready['service']);ready['commit']()
    async def start():return await boot('test',str(directory/'cordis.yml'),read_profile_patches('test',profile),prepare)
    ctx=await start();rows=[]
    try:
        await ctx.plugin(TimerService);await ctx.plugin(ConfigWatcherService,dict(root=[],ignored=[],debounce=0))
        await ctx.hmr.runExclusive(lambda:None)
        editor=ctx.configEditor;settings=ctx.settings
        def snapshot(name):
            descriptor=settings.describe(dict(redactSecrets=True))[0];descriptor.pop('schema');rows.append(dict(name=name,value=descriptor))
        snapshot('initial');rows.append(dict(name='entries',values=[entry.options['id'] for entry in editor.entries()]))
        await settings.update('probe',dict(count=3));snapshot('updated')
        text=(directory/'cordis.patch.yml').read_text(encoding='utf-8')
        rows.append(dict(name='comments',values=[marker in text for marker in ('# profile','# identity','# module','# configuration','# tail')]))
        await asyncio.gather(settings.update('probe',dict(count=4)),settings.update('probe',dict(token='rotated')))
        rows.append(dict(name='serialized-edits',value=next(row for row in editor.entries() if row.options['id']=='probe').fiber.effectiveConfig['count'].get(),
            token=next(row for row in editor.entries() if row.options['id']=='probe').fiber.effectiveConfig['token'].get()))
        rows.append(dict(name='disk',value=json.loads(json.dumps(__import__('yaml').safe_load((directory/'cordis.patch.yml').read_text(encoding='utf-8'))))))
        entry=next(entry for entry in editor.entries() if entry.options['id']=='probe')
        await editor.edit(entry,lambda current,base:dict(current,ordinary='changed'));snapshot('ordinary-edit')
        before=(directory/'cordis.patch.yml').read_text(encoding='utf-8')
        try:await editor.edit(entry,lambda current,base:dict(current,ordinary='rejected'))
        except Exception:rows.append(dict(name='activation-rollback',unchanged=(directory/'cordis.patch.yml').read_text(encoding='utf-8')==before,
            ordinary=next(row for row in editor.entries() if row.options['id']=='probe').fiber.effectiveConfig['ordinary']))
        # An invalid live value is refused before publication.
        try:await settings.update('probe',dict(count=0))
        except Exception:rows.append(dict(name='invalid-refusal',unchanged=(directory/'cordis.patch.yml').read_text(encoding='utf-8')==before))
        profile['overlays']=[dict(id='probe',config=dict(ordinary='changed',count=7,token='private'))]
        try:await settings.update('probe',dict(count=4))
        except Exception as error:rows.append(dict(name='overlay-refusal',message=str(error),unchanged=(directory/'cordis.patch.yml').read_text(encoding='utf-8')==before))
        profile['overlays']=[]
    finally:await ctx.fiber.dispose()
    ctx=await start()
    try:
        descriptor=ctx.settings.describe(dict(redactSecrets=True))[0];rows.append(dict(name='restart',value=descriptor['value']))
        await ctx.settings.mutate('probe',[dict(op='unset',path=['count'])]);rows.append(dict(name='reset',value=ctx.settings.describe(dict(redactSecrets=True))[0]['value']))
    finally:await ctx.fiber.dispose()
    (root/'settings.yaml').write_text('probe:\n  count: 6\nmissing:\n  enabled: true\n',encoding='utf-8')
    ctx=await start()
    try:
        async def imported():
            while ctx.settings.describe()[0]['value']['count']!=6:
                await asyncio.sleep(0.01)
        await asyncio.wait_for(imported(),10)
        rows.append(dict(name='legacy-import',renamed=not (root/'settings.yaml').exists() and (root/'settings.yaml.imported').exists(),value=ctx.settings.describe()[0]['value']['count']))
    finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_settings_lifecycle.mts','Real profile settings lifecycle: HMR serialized edits, row comments, ConfigEditor rollback/restart and legacy settings rename/import with rejected section. Exact YAML formatting is not compared.',[Path(__file__).resolve(),ROOT/'dsh/boot/config_editor.py',ROOT/'dsh/settings/forms.py',ROOT/'dsh/util/atomic_write.py'],prepare=prepare,node_args=('--expose-internals',))
