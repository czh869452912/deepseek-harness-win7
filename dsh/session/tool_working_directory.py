"""Read or change the exact calling Session's current working directory."""
from dsh.cordis.plugin import Plugin
from dsh.core.tools import ToolArgsError, ToolContextUnavailableError


class ToolWorkingDirectory(Plugin):
    inject = ['tools', 'workingDirectory']

    def apply(self, ctx):
        async def execute(arguments, execution):
            if execution.agent is None:
                raise ToolContextUnavailableError('working_directory requires an agent Session')
            if arguments.get('cd') == '':
                raise ToolArgsError('working_directory', ['cd must not be empty; omit it to read the current directory'])
            directories = ctx.get('workingDirectory')
            cwd = (await directories.set(execution.agent, arguments['cd'], execution.signal) if 'cd' in arguments
                   else await directories.ensure(execution.agent, execution.signal))
            return dict(cwd=cwd)
        ctx.get('tools').register(dict(name='working_directory',
            description='Read the current working directory, or change it with cd. Relative paths use the current directory. Existing shells and running processes keep their own directories.',
            parameters=dict(type='object', properties=dict(cd=dict(type='string', description='Existing directory to enter. Omit to read the current directory.'))),
            output=dict(schema=dict(type='object', additionalProperties=False, properties=dict(cwd=dict(type='string', description='Current absolute working directory.')), required=['cwd']),
                        render=lambda _, value: [dict(type='text', text=value['cwd'])]), execute=execute))
