import asyncio
from types import SimpleNamespace as NS

import pytest

from scripts import rc022_sdk_lineage_probe as probe
from dsh.subagent.lifecycle_current import observe_run, ActivationObserver


@pytest.mark.asyncio
async def test_actual_sdk_nested_direct_creator_and_locality(tmp_path):
    previous=probe.WORKSPACE;probe.WORKSPACE=tmp_path
    try:rows={row['name']:row for row in await probe.observe()}
    finally:probe.WORKSPACE=previous
    notes=rows['actual-nested']['notifications']
    assert [(row['params']['childSessionId'],row['params']['parentSessionId']) for row in notes]==[('child','root'),('grandchild','child'),('grandchild','child'),('child','root')]
    assert rows['actual-nested']['live']==[True,False,False]
    assert rows['origin-filter']['notifications']==[dict(method='subagent.started',params=dict(parentSessionId='creator',childSessionId='subagent'))]
    finished=rows['payload-owned']['notifications']
    assert len(finished)==1 and finished[0]['params']['parentSessionId']=='direct-parent'
    assert finished[0]['params']['lastAssistantMessage']==[dict(type='text',text='retained')]


@pytest.mark.asyncio
async def test_one_shot_and_epoch_helpers_snapshot_direct_creator():
    events=[];parent=NS(session=NS(id='direct'))
    result=asyncio.get_running_loop().create_future();run=NS(id='child',result=result,localAgent=object())
    observe_run(lambda *args:events.append(args),'provider',parent,run)
    parent.session.id='changed'
    result.set_result(dict(stopReason='completed',output=[]));await asyncio.sleep(0)
    assert [event[1]['parentSessionId'] for event in events]==['direct','direct']
    observer=ActivationObserver(lambda *args:events.append(args),'provider','epoch',parent)
    parent.session.id='changed-again';observer.settle()
    assert events[-1][1]['parentSessionId']=='changed'
