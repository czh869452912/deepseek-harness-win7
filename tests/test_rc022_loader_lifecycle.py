import asyncio
from scripts import rc022_loader_lifecycle_probe as probe


def test_raw_identity_failed_activation_and_disabled_handle_contracts():
    result=asyncio.run(probe.native())
    assert result['noop']==dict(same_options=True,entry_raw=True,fiber_raw=True,disabled=False,calls=[1],partials=[])
    assert result['failed']==dict(errors=['fiber'],state=3,calls=[1])
    assert result['import']==dict(errors=[],fiber=False)
    assert result['name']==dict(name='cordis:other',same_fiber=True,calls=[1,2],partials=[True,True])
    assert result['disabled']==dict(retained=True,disposed=True,partials=[],new_fiber=True,calls=[1,1])
    assert result['create']==dict(new_options=True,same_fiber=True,fiber_raw=True,calls=[1],partials=[True])
    assert result['init-gate']==dict(before=0,after=2,calls=['active'])
    assert result['update-gate']==dict(before=0,after=0,calls=[])
