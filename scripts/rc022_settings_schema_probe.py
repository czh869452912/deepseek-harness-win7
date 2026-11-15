"""Pair volatile schema projection without claiming editor integration."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis.schema import Schema as z
    from dsh.settings.schema_current import volatile_form, project_form, plain_config, is_volatile_path
    nested=z.object(dict(ordinary=z.string(),nested=z.object(dict(fixed=z.string(),live=z.number().volatile())),enabled=z.boolean().volatile()))
    container=z.object(dict(secret=z.string().role('secret').default('hidden').required(),
        rows=z.array(z.object(dict(name=z.string(),token=z.string().role('secret')))).default([dict(name='one',token='hidden')]),
        mode=z.union(['one','two']).default('one'))).volatile()
    form=volatile_form(nested);full=volatile_form(container)
    return [dict(name='nested',schema=form.toJSON(),value=project_form(form,dict(ordinary='hidden',nested=dict(fixed='hidden',live=3),enabled=True))),
        dict(name='container',schema=full.toJSON(),value=plain_config(container(dict(secret='private',rows=[dict(name='two',token='private')])))),
        dict(name='paths',values=[is_volatile_path(nested,path) for path in (['nested','live'],['nested','fixed'],[])]+[is_volatile_path(container,['rows','0','token'])]),
        dict(name='expression',value=project_form(form,dict(nested=dict(__jsExpr='ctx.live')))),
        dict(name='empty',form=volatile_form(z.object(dict(fixed=z.string()))),value=project_form(z(dict(type='object')),dict(undeclared=True))),
        dict(name='null',value=project_form(full,None)),
        dict(name='original',secretDefault=container.dict['secret'].meta['default'],volatile=container.meta['volatile'])]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_settings_schema.mts','Actual Schema/Volatile and settings form projection: editable ancestor selection, secret-default redaction, expression preservation and detached plain values. No ConfigEditor or profile persistence claim.',[Path(__file__).resolve(),ROOT/'dsh/settings/schema_current.py'])
