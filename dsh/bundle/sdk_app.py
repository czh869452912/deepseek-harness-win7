"""SDK command grammar and readiness, independent of the stdio transport."""
from dsh.boot.cmdline import Command, parse_cmdline, exit_on_stdin_end, internals
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema


class SdkAppStartup(Plugin):
    id = 'sdk-app-startup'
    inject = ['cmdlineArgs']
    Config = Schema.object({'profile': Schema.string().default('sdk')})

    def apply(self, ctx):
        profile = self.config.get('profile', 'sdk')
        program = (Command().name('dsh --profile ' + profile)
                   .description('Serve DeepSeek Harness SDK clients over stdio JSON-RPC.')
                   .helpOption('-h, --help', 'show this help')
                   .addHelpText('after', '\nExample:\n  dsh --profile ' + profile
                                + '     serve one SDK runtime until its client disconnects\n'))

        def accepted():
            if program.args:
                program.error('error: too many arguments. Expected 0 arguments but got {}.'.format(len(program.args)))
            stdin = internals.stdin
            if not hasattr(stdin, 'on'):
                from dsh.sdk.stdio import StdioInput
                stdin = StdioInput(stdin)
                ctx.effect(lambda: stdin.close)
            ctx.provide('sdkStdin', stdin)
            exit_on_stdin_end(ctx, 'sdk-app.stdin', stdin)
            ctx.provide('sdkAppStartup', {'accepted': True})

        program.action(accepted)
        parse_cmdline(ctx, program)
