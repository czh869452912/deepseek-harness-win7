import asyncio
import pytest
from dsh.cordis.context import Context
from dsh.cordis.events import AggregateError
from dsh.cordis.fiber import FiberState
from dsh.cordis.schema import Schema
from dsh.cordis.timer import TimerService


def test_context_static_symbols_and_is():
    ctx = Context(base_url='https://api.deepseek.com')
    assert Context.is_(ctx) is True
    assert Context.is_context(ctx) is True
    assert Context.is_(None) is False
    assert Context.is_('string') is False

    assert ctx.base_url == 'https://api.deepseek.com'
    assert ctx.baseUrl == 'https://api.deepseek.com'

    child = ctx.extend()
    assert child.base_url == 'https://api.deepseek.com'
    assert child.baseUrl == 'https://api.deepseek.com'
    assert Context.is_(child) is True


def test_schemastery_i18n_hierarchical_localization():
    schema = Schema.object({
        'username': Schema.string().description('Default username'),
        'timeout': Schema.number().description('Connection timeout'),
    }).description('Server configuration')

    localized = schema.i18n({
        'zh': {
            '': 'Server Config ZH',
            'username': 'Username ZH',
            'timeout': 'Timeout ZH',
        },
        'ja': {
            '': 'Server Config JA',
            'username': 'Username JA',
            'timeout': 'Timeout JA',
        }
    })

    assert isinstance(localized.meta['description'], dict)
    assert localized.meta['description'].get('zh') == 'Server Config ZH'
    assert localized.meta['description'].get('ja') == 'Server Config JA'
    assert localized.dict['username'].meta['description'].get('zh') == 'Username ZH'
    assert localized.dict['timeout'].meta['description'].get('zh') == 'Timeout ZH'


@pytest.mark.asyncio
async def test_parallel_dispatch_aggregate_error():
    ctx = Context()

    def fail_one():
        raise ValueError('error one')

    def fail_two():
        raise RuntimeError('error two')

    ctx.on('test/fail', fail_one)
    ctx.on('test/fail', fail_two)

    with pytest.raises(AggregateError) as exc_info:
        await ctx.parallel('test/fail')

    assert len(exc_info.value.errors) == 2
    err_msgs = [str(e) for e in exc_info.value.errors]
    assert any('error one' in m for m in err_msgs)
    assert any('error two' in m for m in err_msgs)


@pytest.mark.asyncio
async def test_timer_async_iterator_and_disposal():
    ctx = Context()
    ticks = []

    async def _consume():
        async for _ in ctx.timer.interval(10):
            ticks.append(len(ticks) + 1)
            if len(ticks) >= 3:
                break

    await _consume()
    assert ticks == [1, 2, 3]
