"""Actual Loader candidate graph for focused application integration checks."""
import json
from dsh.boot.app_boot import boot
from dsh.boot.plugin_registry import _load,HARNESS_PLUGIN_CLASSES
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES
from scripts.oracles.agent_machine_current_python import ScriptAdapter


async def setup(root,extra=(),script=(),prepare=None):
    config=root/'candidate.json';config.write_text('[]',encoding='utf-8')
    specifications=[('agent',{}),('session',{}),('llm',{}),('tools',{}),('tool-executor-native',{}),('system-prompt',{}),
        ('working-directory',dict(defaultDirectory=str(root))),('session-projection',{}),('fs-local',dict(cwd=str(root))),
        ('session-persistence-jsonl',dict(root=str(root/'sessions'),compression='none')),('session-query-sqlite',dict(path=':memory:',openAt='never')),('agent-loop',dict(agents=[]))]
    specifications.extend(extra)
    rows=[dict(id=spec[2] if len(spec)>2 else spec[0],name='@deepseek-ai/dsh-'+spec[0],config=spec[1]) for spec in specifications]
    assert len({row['id'] for row in rows})==len(rows)
    def configure(ctx):
        for row in rows:
            name=row['name'];ctx.loader.harness_plugins[name]=_load(name,CURRENT_HARNESS_PLUGIN_CLASSES.get(name,HARNESS_PLUGIN_CLASSES.get(name)))
        ctx.inject(['llm'],lambda child:child.llm.registerAdapter(['script'],ScriptAdapter(dict(script=list(script)))))
        if prepare is not None:return prepare(ctx)
    (root/'candidate-inputs.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    return await boot('candidate-integration',str(config),[dict(insert=rows)],configure)
