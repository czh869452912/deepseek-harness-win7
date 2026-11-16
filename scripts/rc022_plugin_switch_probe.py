"""Profile enablement edits over real bundle layers and retained YAML syntax."""
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


def corpus():
    tool=dict(id='tool',name='package')
    def case(name,text,actions=(False,False,True),rows=None):
        return dict(name=name,text=text,actions=actions,rows=[tool] if rows is None else rows)
    return [
        case('missing',None),case('empty','[]\n'),
        case('comment-expression','# personal configuration\n- id: tool\n  config:\n    value: !!js process.platform\n- id: tool\n  disabled: false # availability\n'),
        case('insert','- insert:\n    - id: tool\n      name: package\n',rows=[]),
        case('malformed','- id: [broken'),case('mapping','mapping: true\n'),
        case('mismatch','- id: tool\n  name: another-package\n  disabled: false\n'),
        case('named-last','- id: tool\n  disabled: true\n- id: tool\n  name: package\n  config: { value: !!js process.platform }\n  disabled: true # availability\n- id: tool\n  name: another-package\n  disabled: true\n',actions=[True,True,False]),
        case('plain','# personal configuration\n- id: other\n  disabled: true\n- id: tool\n  disabled: true\n',actions=[True,True,False]),
        case('other-settings','- id: tool\n  config: { value: 1 }\n  disabled: true\n',actions=[True]),
        case('bundle-disabled','- id: tool\n  disabled: true\n',actions=[True],rows=[dict(tool,disabled=True)]),
        case('header-next','# header\n- id: tool\n  disabled: false\n# other\n- id: other\n  disabled: true\n',actions=[True]),
        case('header-only','# header\n- id: tool\n  disabled: true\n',actions=[True]),
        case('last-comment','- id: other\n  disabled: true\n# about tool\n- id: tool\n  disabled: true\n# tail\n',actions=[True]),
        case('inline-removed','- id: tool\n  disabled: true # removed\n# tail\n',actions=[True]),
        case('anchor-value','- id: &plugin tool\n  disabled: true\n- id: other\n  config: { target: *plugin }\n',actions=[True]),
        case('anchor-map','- &plugin { id: tool, disabled: true }\n- id: other\n  config: { target: *plugin }\n',actions=[True]),
        case('anchor-key','- id: tool\n  &key disabled: true\n- id: other\n  config: { *key : 1 }\n',actions=[True]),
        case('alias-value','- id: other\n  config: { flag: &flag true }\n- id: tool\n  disabled: *flag\n',actions=[True]),
        case('anchored-disabled','- id: tool\n  disabled: &flag true\n- id: other\n  config: { flag: *flag }\n',actions=[True]),
        case('flow-root','[{id: tool, disabled: true}, {id: other, config: {count: 8}}]\n',actions=[True,False]),
        case('flow-map','- { id: tool, config: {count: 8} } # note\n'),
        case('flow-root-add','[{id: other, config: {count: 8}}]\n'),
        case('duplicate','- id: tool\n  disabled: false\n  disabled: true\n'),
        case('expression-disabled','- id: tool\n  disabled: !!js ctx.ready\n',actions=[True]),
        case('nested-group','[]\n',rows=[dict(id='group',group=True,config=[tool])]),
        case('overridden','- id: tool\n  disabled: true\n',actions=[True],rows=[tool]),
        case('no-inherited-entry','- id: tool\n  disabled: true\n',actions=[True],rows=[]),
        case('null-disabled','- id: tool\n  disabled: null\n',actions=[True]),
        case('alias-map','- &switch { id: other, disabled: true }\n- *switch\n'),
        case('bundle-null','- id: tool\n  disabled: true\n',actions=[True],rows=[dict(tool,disabled=None)]),
        case('bundle-condition','- id: tool\n  disabled: true\n',actions=[True],rows=[dict(tool,disabled=dict(__jsExpr='ctx.ready'))]),
    ]


async def observe(workspace=None):
    import yaml
    from dsh.boot.plugin_switch import write_plugin_enabled
    from dsh.boot.app_boot import load_optional_patches
    output=[]
    for case in corpus():
        home=(workspace or WORKSPACE)/'native'/case['name'];directory=home/'profile';bundle=directory/'node_modules/bundle';bundle.mkdir(parents=True)
        def write(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        write(home/'package.json',dict(name='installation'))
        write(directory/'package.json',dict(name='profile',dsh=dict(profile=dict(bundles=['bundle']))))
        write(bundle/'package.json',dict(name='bundle',version='1.0.0',dsh=dict(bundle=dict(patch='cordis.patch.yml'))))
        write(bundle/'cordis.patch.yml',[dict(insert=case['rows'])])
        filename=directory/'cordis.patch.yml'
        if case['text'] is not None:filename.write_text(case['text'],encoding='utf-8')
        # Home and launch overrides must not influence redundant-switch pruning.
        write(home/'cordis.patch.yml',[dict(id='tool',disabled=True)])
        profile=dict(name='test',dir=str(directory),patchPath=str(filename),installAnchor=str(home/'package.json'),cwd=str(home),home=str(home),startedBundles=['bundle'],overlays=[dict(id='tool',disabled=True)])
        steps=[]
        for enabled in case['actions']:
            before=filename.read_text(encoding='utf-8') if filename.exists() else None
            try:
                changed=await write_plugin_enabled(profile,'tool','package',enabled)
                text=filename.read_text(encoding='utf-8') if filename.exists() else None
                steps.append(dict(changed=changed,patches=load_optional_patches('test',str(filename)),comments=re.findall(r'#[^\n]*',text or ''),expression='!!js process.platform' in (text or ''),unchanged=before==text))
            except Exception:
                text=filename.read_text(encoding='utf-8') if filename.exists() else None
                steps.append(dict(refused=True,unchanged=before==text))
        output.append(dict(name=case['name'],steps=steps))
    return output


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir()
    path=output/'input.json';path.write_text(json.dumps(dict(workspace=str(WORKSPACE),cases=corpus())),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_plugin_switch.mts','Actual writePluginEnabled over real selected bundle and profile files: last eligible override, redundant literal switch pruning, comments/tags/anchors/aliases, insertions/groups, malformed/duplicate document refusal, no home/overlay influence, atomic persistence and idempotence. Compare parsed patch values and retained comments/tags, not formatting normalization of changed YAML collections.',[Path(__file__).resolve(),ROOT/'dsh/boot/plugin_switch.py'],prepare=prepare)
