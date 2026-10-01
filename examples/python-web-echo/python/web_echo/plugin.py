from dsh.plugin_api import Plugin, Remote, TypertRemoteService


class WebEchoService(TypertRemoteService):
    def __init__(self, ctx):
        super().__init__(ctx, 'pythonWebEcho')
        self.calls = 0

    @Remote
    async def echo(self, text):
        self.calls += 1
        return dict(text='Python Web echo: ' + text, calls=self.calls, version='1.0.0')


class WebEchoPlugin(Plugin):
    def apply(self, ctx, config):
        WebEchoService(ctx)
