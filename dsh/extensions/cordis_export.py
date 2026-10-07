"""Python-specific model tool; upstream Cordis tool contracts stay unchanged."""
from dsh.boot.python_plugin_export import export_project, json_text
from dsh.cordis.plugin import Plugin


class PythonPluginExport(Plugin):
    id = 'tool-python-export'
    inject = ['tools', 'dynamicCordisRunner', 'fs']

    def apply(self, ctx):
        register_export_tool(ctx)


def register_export_tool(ctx):
    strings = {key: dict(type='string') for key in (
        'pluginId', 'packageId', 'directory', 'name', 'version', 'license', 'licenseText')}
    strings['directory']['description'] = 'New relative project directory inside this session workspace; never overwritten.'
    strings['name']['description'] = 'Stable author-owned package identity, separate from the dynamic plugin ID.'
    strings['placement'] = dict(type='string', enum=['host', 'session'])
    strings['isolateServices'] = dict(type='array', items=dict(type='string'),
        description='For session placement, isolate every additional service provided by the Host code.')
    definition = dict(name='cordis_export', description=(
        'Export an exact owned dynamic plugin version to a native Python source project. '
        'Host projects install with the existing Python directory/ZIP installer. Session projects '
        'include a user-preset fragment. Client source is retained but requires later build support; '
        'such projects cannot yet be installed. Supply explicit license text. Review and test before sharing.'),
        parameters=dict(type='object', properties=strings,
            required=[key for key in strings if key != 'isolateServices'], additionalProperties=False),
        output=dict(schema=dict(type='object', properties={
            **{key: dict(type='string') for key in ('name', 'version', 'directory', 'pluginId', 'packageId', 'placement')},
            'files': dict(type='array', items=dict(type='string')), 'requiresClientBuild': dict(type='boolean')},
            required=['name', 'version', 'directory', 'pluginId', 'packageId', 'placement', 'files', 'requiresClientBuild'],
            additionalProperties=False), render=lambda args, value: [dict(type='text', text=json_text(value))]),
        execute=lambda args, execution: export_project(ctx, args, execution),
        presentCall=lambda args: dict(card='generic', kind='edit', title='Export Python plugin ' + args['name']))
    ctx.get('tools').register(definition)
