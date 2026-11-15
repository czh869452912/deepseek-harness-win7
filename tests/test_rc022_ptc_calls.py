import pytest
from scripts.rc022_ptc_calls_probe import observe


@pytest.mark.asyncio
async def test_ptc_calls_wait_for_cleanup_reset_and_owner_disposal():
    rows={row['action']:row for row in await observe()}
    assert all(row['unrelatedIgnored'] for row in rows.values())
    for action in ('policy','external-abort','waiting-abort','reset','release-fails','notify-fails','dispose','dispose-reset'):
        assert rows[action]['aborted'] and rows[action]['blocked']
    assert not rows['no-policy']['aborted'] and not rows['no-policy']['blocked']
    assert rows['policy']['trace'].index('cleanup') < rows['policy']['trace'].index('mode:danger-full-access')
    assert rows['waiting-abort']['next']==dict(message='waiting canceled',code=None)
    assert rows['failed-call']['overlap']
    for action in ('reset','release-fails','notify-fails','dispose-reset'):
        assert rows[action]['sharedReset'] and rows[action]['releaseInsufficient']
        assert rows[action]['independent']=='independent'
    for action in ('release-fails','notify-fails'):
        assert rows[action]['blockedAfterFailure']['code']=='CODE_RUN_FAILED'
        assert rows[action]['retry']=='next'
    for action in ('dispose','dispose-reset'):
        assert rows[action]['lateReset']==dict(message='PTC tool executor disposed',code=None)


@pytest.mark.asyncio
async def test_failed_authority_lookup_releases_signal_relays():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.ptc_calls import PtcCalls
    ctx=Context();calls=PtcCalls(ctx);controller=AbortController()
    before=len(controller.signal._listeners)
    def mode():raise RuntimeError('authority failed')
    with pytest.raises(RuntimeError,match='authority failed'):
        await calls.run('session',controller.signal,mode,lambda signal:None)
    assert not calls.calls and len(controller.signal._listeners)==before
    await ctx.fiber.dispose()
