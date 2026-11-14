import asyncio
from scripts import rc022_logger_probe as probe


def test_severity_exporter_ownership_and_record_isolation():
    result=asyncio.run(probe.native())
    full=[['error',0,1],['warn',1,2],['info',2,3],['debug',3,4]]
    assert result['levels']==[full[:3],full[:1],full[:2],full[:3],full]
    assert result['disposer']==[False,True]
    assert result['records']==[True,'named',[None,'shared'],'named']
    assert result['empty_aggregate']==1
    assert result['meta']==['override',9,123,['actual','shared']]
    assert result['buffer']==[True,2,[2,3]]
    # The bootstrap buffer exporter survives; owned user exporters are gone.
    assert result['empty_name']=='' and result['disposed']==1
