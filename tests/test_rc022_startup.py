import asyncio
import pytest
from scripts import rc022_startup_probe as probe


def test_actual_boot_keeps_optional_siblings_and_bounds_failure_evidence(tmp_path):
    probe.OUTPUT=tmp_path
    result=asyncio.run(probe.native())
    for mode in ('optional','missing','disabled'):
        assert not result[mode]['fatal'] and not result[mode]['disposed']
    for mode in ('required','pending','isolated','root','bounded'):
        assert result[mode]['fatal'] and result[mode]['disposed'] and result[mode]['startup_path']
    assert result['required']['original_cause'] and result['required']['cleanup_log']
    assert result['isolated']['composition']['services'][0]['providers'][0]['visibility']=='other-scope'
    bounded=result['bounded']['composition']
    assert len(bounded['plugins'])==len(bounded['services'])==256
    assert bounded['omittedPlugins']==4 and bounded['omittedServices']==1
    assert not any(row['private'] for row in result.values())


@pytest.mark.asyncio
async def test_unavailable_composition_keeps_original_startup_error_and_cleanup_logs(tmp_path):
    from dsh.boot import boot, StartupError
    failure = StartupError('interrupted', [])
    async def prepare(ctx):
        await ctx.fiber.dispose()
        raise failure
    with pytest.raises(StartupError) as caught:
        await boot('probe', str(tmp_path/'root.json'), prepare=prepare)
    assert caught.value is failure and failure.composition is None
    assert any(message['args'][0] == 'Startup composition diagnostic unavailable'
        for message in failure.startup['messages'])


@pytest.mark.asyncio
async def test_cyclic_setup_cause_terminates_and_preserves_original_error(tmp_path):
    from dsh.boot import boot
    failure = RuntimeError('cycle')
    failure.__cause__ = failure
    def prepare(ctx):
        raise failure
    with pytest.raises(RuntimeError, match='host preparation failed: cycle') as caught:
        await asyncio.wait_for(boot('probe', str(tmp_path/'root.json'), prepare=prepare), 2)
    assert caught.value.__cause__ is failure
