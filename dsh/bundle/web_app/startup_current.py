"""Current Web CLI flags, published before lazy runtime configuration."""
import json
import math
import re

from dsh.boot.cmdline import Command, parse_cmdline
from dsh.bundle.web_app.current import parse_public_url
from dsh.bundle.web_app.startup import WebStartupValues
from dsh.cordis.plugin import Plugin
from dsh.host.webserver.bind import is_wildcard_host


class CurrentWebStartupValues(WebStartupValues):
    __slots__ = ('publicUrl', 'tls')

    def to_dict(self):
        values=super().to_dict()
        for key in ('publicUrl','tls'):
            if hasattr(self,key):values[key]=getattr(self,key)
        return values


def web_command():
    return (Command().name('dsh --profile web').description('Serve the DeepSeek Harness browser UI.')
        .helpOption('-h, --help','show this help')
        .option('--host <host>','bind address: one concrete IPv4 or IPv6 literal of a local interface; wildcard addresses are rejected')
        .option('--no-open','do not open the Web UI in the default browser')
        .option('--port <port>','listen port; pass 0 to let the OS pick a free one')
        .option('--public-url <url>','advertise this HTTP(S) root in the printed, opened, runtime-context, and DSH_WEB_URL forms; grants no trust')
        .option('--trusted-host <authority...>','extra authority the /api browser-trust fence accepts (host or host:port; repeatable)')
        .option('--tls-cert <file>','PEM server certificate chain; requires --tls-key')
        .option('--tls-key <file>','unencrypted PEM private key; requires --tls-cert')
        .addHelpText('after','\nExamples:\n'
            '  dsh --profile web                          serve on the composed host and port\n'
            '  dsh --profile web --no-open                serve without opening a browser\n'
            '  dsh --profile web --port 8080              serve on another port\n'
            '  dsh --profile web --host 10.0.0.7          bind one local interface address\n'
            '  dsh --profile web --public-url https://app.example/ui/ --trusted-host app.example\n'
            '                                             advertise a prefix-stripping HTTPS proxy entry and admit its authority\n'
            '  dsh --profile web --tls-cert ./server-chain.pem --tls-key ./server-key.pem\n'
            '                                             serve HTTPS with an existing certificate and key\n'))


class CurrentWebStartup(Plugin):
    id='web-startup'
    inject=['cmdlineArgs']
    Config=None

    def apply(self,ctx):
        program=web_command()
        def action():
            options=program.opts();host=options.get('host');port=options.get('port')
            if host is not None and is_wildcard_host(host):
                program.error('error: --host '+host+' is an unspecified (wildcard) address, which is not supported: binding every interface would expose remote code execution to the network; bind one concrete IPv4 or IPv6 address instead')
            if port is not None and re.fullmatch(r'[0-9]+',port) is None:
                program.error('error: --port must be a number, got '+json.dumps(port,ensure_ascii=False))
            cert,key=options.get('tlsCert'),options.get('tlsKey')
            if (cert is None)!=(key is None):
                program.error('error: --tls-cert and --tls-key must be supplied together')
            public=options.get('publicUrl')
            if public is not None:
                try:parse_public_url(public,'--public-url')
                except ValueError as error:program.error('error: '+str(error))
            number=float(port) if port is not None else None
            values=CurrentWebStartupValues(open_browser=options['open'],host=host,
                port=int(number) if number is not None and math.isfinite(number) else number,
                trusted_hosts=options.get('trustedHost'))
            if public is not None:values.publicUrl=public
            if cert is not None:values.tls=dict(certFile=cert,keyFile=key)
            ctx.set_service('webStartup',values)
        program.action(action)
        parse_cmdline(ctx,program)
