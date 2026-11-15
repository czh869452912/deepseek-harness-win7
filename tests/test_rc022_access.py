from types import SimpleNamespace as NS
import pytest

from dsh.cordis import Context
from dsh.cordis.plugin import Plugin
from dsh.typert.current import CurrentTypertRegistry
from dsh.typert.access import call_resources, event_resources
from scripts.rc022_access_probe import observe


@pytest.mark.asyncio
async def test_wire_resources_reject_malformed_and_preserve_precedence():
    rows = {row['name']: row['value'] for row in await observe()}
    assert rows['global'] == [dict(kind='global')]
    assert rows['nested'] == [dict(kind='shelf', id='nested')]
    assert rows['first-object-only'] == [dict(kind='global')]
    assert rows['top-level-wins'] == [dict(kind='shelf', id='top')]
    assert rows['resolver-throw'] is None
    assert rows['lookup-malformed'] is None
    assert rows['context-before-lookups'] == [dict(kind='shelf', id=value) for value in ['context', 'a', 'b']]
    assert rows['kind-order-reader-wins'] == [dict(kind='shelf', id='read'), dict(kind='desk', id='d'), dict(kind='frame', id='f')]
    assert rows['positional-wire-order'] == [dict(kind='shelf', id='A')]
    assert rows['cancellation-slot'] == [dict(kind='shelf', id='signal')]
    assert rows['ownership']['frozen'] and rows['ownership']['empty']
    assert rows['ownership']['changes'] == [dict(kind='resource', key='shelf')] * 2


@pytest.mark.asyncio
async def test_resource_views_belong_to_calling_fiber_and_metadata_survives_resolver():
    ctx = Context(); await ctx.plugin(CurrentTypertRegistry)
    class Owner(Plugin):
        inject = ['typert']
        def apply(self, child):
            self.registry = child.typert
            child.typert.resources.register('session', dict(field='sessionId'))
    try:
        first = await ctx.plugin(Owner)
        assert ctx.typert.resources.get('session') == dict(field='sessionId')
        await first.dispose()
        assert ctx.typert.resources.get('session') is None
        second = await ctx.plugin(Owner)
        # Disposing an old, already-withdrawn owner cannot remove its replacement.
        await first.dispose()
        assert second.plugin.registry.resources.get('session') == dict(field='sessionId')
        ctx.typert.lookups.register('session', NS(parameter='session', wire='sessionId', hostTypeSymbol='host', wireTypeSymbol='wire', resource='session', resolve=lambda value:value))
        second.plugin.registry.lookups.configure('session', lambda value:'changed:' + value)
        assert ctx.typert.lookups.get('session').resource == 'session'
        assert await ctx.typert.lookups.get('session').resolve('s') == 'changed:s'
        await second.dispose()
        assert ctx.typert.lookups.get('session').resource == 'session'
        assert ctx.typert.lookups.get('session').resolve('s') == 's'
    finally:
        await ctx.fiber.dispose()


def test_event_undefined_differs_from_absent_readers_and_global_is_defensive_copy():
    from dsh.core.session.json import UNDEFINED
    assert event_resources(dict(session=lambda *_:UNDEFINED), []) is None
    assert event_resources(dict(session=lambda *_:[]), []) is None
    one = event_resources({}, [])
    one[0]['kind'] = 'mutated'
    assert event_resources(None, []) == [dict(kind='global')]
