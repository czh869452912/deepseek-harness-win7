import json
import os

import pytest

from dsh.client import product_analytics_current as analytics
from dsh.host.desktop.runtime import ROOT,run_desktop_host
from dsh.core.abort import AbortController
from test_rc022_product_telemetry import collectors


def test_app_process_environment_is_scoped_to_its_context(monkeypatch):
    from dsh.cordis import Context
    from dsh.cordis.loader import evaluate_expr
    monkeypatch.setenv('DSH_CLIENT_VERSION','ambient')
    first=Context();second=Context()
    first.provide('nativeProcessEnvironment',dict(DSH_CLIENT_VERSION='app-release'))
    assert evaluate_expr(first,'process.env.DSH_CLIENT_VERSION')=='app-release'
    assert evaluate_expr(second,'process.env.DSH_CLIENT_VERSION')=='ambient'
    assert os.environ['DSH_CLIENT_VERSION']=='ambient'


@pytest.mark.asyncio
@pytest.mark.parametrize('version',[None,'fixture-release'])
async def test_desktop_profile_owns_analytics_context_and_actual_http(collectors,tmp_path,monkeypatch,version):
    monkeypatch.setenv('DSH_HOME',str(tmp_path/'home'))
    monkeypatch.setenv('DSH_TELEMETRY_DISABLED','1')
    collector=collectors();monkeypatch.setenv('DSH_PRODUCT_ANALYTICS_OTLP_URL',collector.url)
    if version is None:monkeypatch.delenv('DSH_CLIENT_VERSION',raising=False)
    else:monkeypatch.setenv('DSH_CLIENT_VERSION',version)
    async def environment(options):return dict(os_name='windows',app_arch='x64',missing_fields={})
    monkeypatch.setattr(analytics,'collectEnvironment',environment)
    runtime=await run_desktop_host(tmp_path/'project')
    try:
        ctx=runtime.ctx;service=ctx.get('productAnalytics')
        assert service is not None and service.enabled() is True
        assert ctx.get('profileContext')['name']=='desktop'
        assert ctx.get('profileContext')['dir']==str(tmp_path/'project')
        assert ctx.get('pluginPackages').resolution is not None
        assert ctx.get('pluginManager') is not None
        assert ctx.get('productTelemetry') is not None and ctx.get('otel') is not None
        assert ctx.get('sessionTelemetry') is None
        assert not collector.hits
        request=dict(type='client-request',rpcId='policy',method='productAnalytics/enabled',payload=dict(args={}))
        response=await runtime.fetch(dict(url='dsh-app://app/api/productAnalytics/enabled',method='POST',
            headers={'content-type':'application/json'},body=json.dumps(request).encode('utf-8'),signal=AbortController().signal))
        assert response['status']==200
        assert json.loads(response['body'])['result']==dict(ok=True,value=True)
        stream_request=dict(endpoint='productAnalytics/watchPolicy',payload=dict(args={}))
        stream=await runtime.fetch(dict(url='dsh-app://app/.dsh/remote-stream',method='POST',
            body=json.dumps(stream_request).encode('utf-8'),signal=AbortController().signal))
        iterator=stream['body'].__aiter__()
        try:assert json.loads(await iterator.__anext__()) is True
        finally:await iterator.aclose()
        assert not service.listeners
        await service.report(dict(eventName='desktop_app_launch',timestamp=1800000000000,attributes={}))
        assert not collector.hits
        # A live user edit must retain the app's socket-free composition and
        # release stamp, while allowing application policy to be replaced.
        patch=tmp_path/'project'/'cordis.patch.yml'
        replacement=patch.with_suffix('.next')
        replacement.write_text('- id: product-analytics\n  config:\n    enabled: false\n    appVersion: policy-edit\n',encoding='utf-8')
        replacement.replace(patch)
        hmr=ctx.get('hmr')
        await hmr.runExclusive(lambda:hmr.reconcileProfile())
        assert ctx.get('productAnalytics').enabled() is False
        assert ctx.get('productAnalytics').config['appVersion']=='policy-edit'
        assert ctx.get('webServer') is None
        assert ctx.get('connection') is not None
    finally:await runtime.close()
    assert len(collector.hits)==1 and collector.hits[0]['channel']=='dsh_otel_report'
    resource=collector.hits[0]['document']['resourceLogs'][0]
    selected=version or json.loads((ROOT/'apps/desktop/package.json').read_text(encoding='utf-8'))['version']
    attributes={item['key']:item['value']['stringValue'] for item in resource['scopeLogs'][0]['logRecords'][0]['attributes']}
    assert attributes['app_version']==selected
    resource_attributes={item['key']:item['value']['stringValue'] for item in resource['resource']['attributes']}
    assert resource_attributes=={'service.name':'deepseek-harness-desktop','service.version':selected}
