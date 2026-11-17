"""Current model-facing primary-runtime preparation tool."""
import json
import os

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import _UNDEFINED
from dsh.core.cleanup import CleanupPromise
from dsh.host.workspace_runtime_files_current import resolvePrimaryRuntime, installPrimaryRuntime

DESCRIPTION = 'Get absolute paths to bundled Python and library directories, plus bundled Python distribution versions. Node.js and pnpm paths are included when the payload provides them. Python includes numpy, pandas, python-docx, python-pptx, openpyxl, Pillow, lxml, and XlsxWriter. Use these libraries for Office files unless the user or workspace instructions select another environment. When Node.js and pnpm paths are returned, run pnpm with that Node executable and pnpm script path. This does not change PATH or package-manager settings.'
PROPERTIES = dict(
    python=dict(type='string', required=True),
    node=dict(type='string', description='Absent when the payload ships no Node.js.'),
    pnpm=dict(type='string', description='Absent when the payload ships no pnpm.'),
    pythonPackages=dict(type='string', required=True),
    nodePackages=dict(type='string', description='Absent when the payload ships no Node.js.'),
    pythonDistributions=dict(type='object', additionalProperties=True, required=True,
        description='Bundled distribution names and versions recorded in runtime.json; excludes user-installed additions.'))


def _render(_args, value):
    text = json.dumps(json.loads(stringify_json(value)), ensure_ascii=False, indent=2)
    return [dict(type='text', text=text.encode('utf-8', 'backslashreplace').decode('utf-8'))]


class CurrentWorkspaceDependencies(Plugin):
    name = 'tool-workspace-dependencies'
    inject = ['tools']
    Config = Schema.object(dict(source=Schema.string().min(1).required(), root=Schema.string().min(1)))

    def apply(self, ctx):
        source = self.config['source']
        root = self.config.get('root', _UNDEFINED)
        if not os.path.isabs(source) or root is not _UNDEFINED and not os.path.isabs(root):
            raise ValueError('workspace dependencies: source and root must be absolute paths')
        preparation = None

        async def dispose():
            if preparation is not None:
                try:
                    await preparation
                except Exception:
                    pass
        ctx.effect(lambda: dispose)

        def execute(*_args):
            nonlocal preparation
            if preparation is None:
                work = resolvePrimaryRuntime(source) if root is _UNDEFINED else installPrimaryRuntime(source, root)
                async def complete():
                    nonlocal preparation
                    try:
                        return await work
                    except BaseException:
                        preparation = None
                        raise
                preparation = CleanupPromise(complete())
            return preparation

        # Convert Source's field-level required shorthand to the canonical JSON Schema.
        properties = {key: {name: value for name, value in item.items() if name != 'required'}
                      for key, item in PROPERTIES.items()}
        ctx.tools.register(dict(name='load_workspace_dependencies', description=DESCRIPTION,
            parameters=dict(type='object', properties={}), execute=execute,
            output=dict(schema=dict(type='object', additionalProperties=False, properties=properties,
                required=[key for key, item in PROPERTIES.items() if item.get('required')]), render=_render),
            presentCall=lambda *_: dict(card='generic', title='Load workspace dependencies', kind='read')))
