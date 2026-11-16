import json

import pytest

from dsh.boot.app_boot import boot
from dsh.boot.cmdline import provide_cmdline,internals
from dsh.cordis.plugin import Plugin
from scripts.rc022_web_startup_probe import observe


@pytest.mark.asyncio
async def test_current_startup_rejections_optional_fields_tls_and_help(tmp_path):
    rows=await observe()
    assert len(rows)==20
    assert rows[0]['values']==dict(openBrowser=True,trustedHosts=[])
    assert rows[3]['values']['tls']==dict(certFile='chain.pem',keyFile='key.pem')
    assert rows[3]['values']['publicUrl']=='HTTPS://APP.EXAMPLE/ui'
    assert rows[9]['values']['host']=='localhost'  # concrete validation belongs to WebServer Config
    assert 'got "-1"' in rows[11]['out']
    assert rows[12]['values']['port']==65536  # range validation belongs to WebServer Config
    assert rows[16]['out']=='error: --tls-cert and --tls-key must be supplied together\n'
    assert rows[-1]['exits']==[0] and rows[-1]['values'] is None
    assert '--public-url <url>' in rows[-1]['out'] and '--tls-key <file>' in rows[-1]['out']
    (tmp_path/'web-startup-observations.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


@pytest.mark.asyncio
async def test_actual_loader_releases_lazy_startup_consumers(tmp_path):
    class Reader(Plugin):
        inject=['webStartup']
        def apply(self,ctx):ctx.set_service('startupReader',self.config)
    config=tmp_path/'root.yml'
    config.write_text("""- id: reader
  name: '@deepseek-ai/dsh-candidate-startup-reader'
  inject: [webStartup]
  config:
    host: !!js ctx.webStartup.host ?? '127.0.0.1'
    port: !!js ctx.webStartup.port ?? 3080
    publicUrl: !!js ctx.webStartup.publicUrl
    tls: !!js ctx.webStartup.tls
    openBrowser: !!js ctx.webStartup.openBrowser
    trustedHosts: !!js ctx.webStartup.trustedHosts
- id: provider
  name: '@deepseek-ai/dsh-web-app/startup'
""",encoding='utf-8')
    exits=[]
    def prepare(ctx):
        ctx.loader.harness_plugins['@deepseek-ai/dsh-candidate-startup-reader']=Reader
        provide_cmdline(ctx,dict(args=['--no-open','--port','0','--public-url','https://app.example/ui',
            '--tls-cert','chain.pem','--tls-key','key.pem','--trusted-host','app.example'],exit=exits.append))
    ctx=await boot('candidate-startup',str(config),[],prepare)
    try:
        assert not exits
        assert ctx.startupReader==dict(host='127.0.0.1',port=0,publicUrl='https://app.example/ui',
            tls=dict(certFile='chain.pem',keyFile='key.pem'),openBrowser=False,trustedHosts=['app.example'])
        (tmp_path/'web-startup-loader-observations.json').write_text(json.dumps(ctx.startupReader,indent=2),encoding='utf-8')
    finally:await ctx.fiber.dispose()
