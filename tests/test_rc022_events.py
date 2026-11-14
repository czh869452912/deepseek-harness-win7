"""New baseline dispatch and reversible-listener boundaries."""
import pytest

from dsh.cordis import Context, EventBus, EventSymbol


def test_waterfall_continuations_are_independent_and_single_use():
    bus = EventBus(); trace = []; held = []
    def outer(value, next_fn):
        held.append(next_fn);trace.append('outer')
        result = next_fn()
        with pytest.raises(RuntimeError, match=r'next\(\) called multiple times'):
            next_fn()
        return result+'-outer'
    def inner(value, next_fn):
        assert next_fn is not held[0]
        trace.append('inner');return next_fn()+'-inner'
    bus.on('chain',outer);bus.on('chain',inner)
    assert bus.waterfall_sync('chain','input',lambda:'end') == 'end-inner-outer'
    assert trace == ['outer','inner']
    with pytest.raises(RuntimeError, match='multiple times'):
        held[0]()


@pytest.mark.asyncio
async def test_async_next_is_claimed_before_await():
    bus = EventBus();trace=[]
    async def listener(value,next_fn):
        pending=next_fn()
        with pytest.raises(RuntimeError,match='multiple times'):
            next_fn()
        return await pending
    bus.on('chain',listener)
    assert await bus.waterfall('chain',1,lambda:trace.append('end') or 42)==42
    assert trace==['end']


@pytest.mark.asyncio
async def test_parallel_reports_its_own_mode_and_symbol_identity():
    bus=EventBus();left,right=EventSymbol('same'),EventSymbol('same');seen=[];called=[]
    bus.on('internal/dispatch',lambda mode,name,args,receiver:seen.append((mode,name,args)))
    bus.on(left,lambda value:called.append(('left',value)))
    bus.on(right,lambda value:called.append(('right',value)))
    await bus.parallel(left,2)
    bus.emit(right,3)
    assert seen==[('parallel',left,[2]),('emit',right,[3])]
    assert called==[('left',2),('right',3)]


@pytest.mark.parametrize('key',['__proto__','constructor','toString',EventSymbol('once')])
def test_last_disposer_removes_empty_key_and_once_unregisters(key):
    bus=EventBus();calls=[]
    dispose=bus.once(key,lambda: calls.append(1))
    bus.emit(key);bus.emit(key)
    assert calls==[1]
    assert key not in bus._hooks
    assert dispose() is False


@pytest.mark.asyncio
async def test_internal_update_registration_is_owned_effect():
    ctx=Context()
    def plugin(child):
        child.on('internal/update',lambda config,no_save,next_fn:next_fn())
    fiber=ctx.plugin(plugin)
    await fiber
    assert len(fiber._hooks['internal/update'])==1
    assert any(meta.label=='ctx.on("internal/update")' for meta in fiber._effect_metas.values())
    await fiber.dispose()
    assert len(fiber._hooks['internal/update'])==0
