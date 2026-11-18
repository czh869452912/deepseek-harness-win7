"""Native refusal metadata survives real stdout/stderr framing boundaries."""
import json
import pytest
from dsh.boot import python_package_prepare as preparation


@pytest.mark.asyncio
@pytest.mark.parametrize('metadata_stream',['stdout','stderr'])
async def test_interleaved_prose_and_bounded_log_do_not_lose_structured_refusal(tmp_path,monkeypatch,metadata_stream):
    issue=[dict(name='@example/pkg',version='1.0.0',runtimeVersion='0.2.2',requirements={'engines.dsh':'>=99'})]
    document=json.dumps(dict(error=dict(code='ERR_DSH_PLUGIN_INCOMPATIBLE',incompatible=issue)))
    chunks=[(document,metadata_stream),('ERR_DSH_PLUGIN_INCOMPATIBLE prose\n','stderr'),('\n','stdout')]
    forwarded=[]
    async def run(directory,argv,options):
        for text,stream in chunks:options['onOutput'](text,stream)
        return dict(exitCode=1,output='\n',truncated=True)
    monkeypatch.setattr(preparation,'run_package_process',run)
    monkeypatch.setattr(preparation,'package_command',lambda:dict(command='controlled',args=[]))
    async with preparation.prepared_registry_package(str(tmp_path),'@example/pkg',dict(outputBytes=1,onOutput=lambda text,stream:forwarded.append((text,stream)))) as result:
        assert result.candidate is None
        if metadata_stream=='stdout':assert result.result['incompatible']==issue
        else:assert 'incompatible' not in result.result
        assert result.result['output']=='\n' and result.result['truncated']
    assert forwarded==chunks
    assert not (tmp_path/'.dsh-python-downloads').exists()
