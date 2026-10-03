from dsh.boot.cmdline import Command, exit_on_stdin_end, internals, parse_cmdline
from dsh.cordis.plugin import Plugin


class AcpAppStartup(Plugin):
    id = 'acp-app-startup'
    inject = ['cmdlineArgs']

    def apply(self, ctx):
        program = (Command().name('dsh --profile acp')
                   .description('Serve automation clients over Agent Client Protocol stdio.')
                   .helpOption('-h, --help', 'show this help')
                   .addHelpText('after', '\nExample:\n  dsh --profile acp     serve ACP until the client disconnects\n'))

        def accepted():
            if program.args:
                program.error('error: too many arguments. Expected 0 arguments but got {}.'.format(len(program.args)))
            stdin = internals.stdin
            if not hasattr(stdin, 'on'):
                from dsh.sdk.stdio import StdioInput
                stdin = StdioInput(stdin)
                ctx.effect(lambda: stdin.close, label='acp-app.input')
            ctx.provide('acpStdin', stdin)
            exit_on_stdin_end(ctx, 'acp-app.stdin', stdin)
            ctx.provide('acpAppStartup', {'accepted': True})

        program.action(accepted)
        parse_cmdline(ctx, program)
