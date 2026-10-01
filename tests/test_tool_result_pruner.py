"""Pinned tool-result pruner assertions and native lifecycle regressions."""
import json
from pathlib import Path

import pytest

from dsh.boot.plugin_registry import install_harness_plugin_classes
from dsh.compaction.pruner import ToolResultPruner, ToolResultPrunerPlugin, DEFAULTS, PRUNE_MARKER, code_point_length, resolve_config
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader
from dsh.core.session import SessionPlugin, Session
from dsh.core.session.invariant import SessionInvariantPlugin
from dsh.diagnostics.invariants import InvariantRegistry
from dsh.llm.token_meter import TokenMeter, TokenMeterPlugin
from scripts.oracles.pruner_python import append_step, blocks, observe, SMALL

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'scripts/oracles/pruner-cases.json').read_text(encoding='utf-8'))


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=[case['mode'] for case in CASES])
async def test_configuration_content_and_durable_result_contract(case):
    row = await observe(case)
    if case['kind'] == 'config':
        invalid = {'config-zero', 'config-negative-head', 'config-fraction', 'config-string', 'config-boolean',
            'config-array', 'config-object', 'config-stale', 'config-snake', 'config-oversized-output', 'config-infinite-output'}
        if case['mode'] in invalid:
            assert row['error'].startswith('ToolResultPruneConfig: ')
        else:
            assert row['frozen'] and row['defaultsFrozen']
            assert row['defaults'] == dict(thresholdChars=8192, headChars=4096, tailChars=1024)
            for key, default in DEFAULTS.items():
                expected = case['config'].get(key)
                assert row['config'][key] == (default if expected is None else expected)
        if case['mode'] == 'config-negative-zero':
            assert row['negativeZero'] == ['headChars', 'tailChars']
        return
    if case['kind'] == 'loader':
        if case['recipe'] == 'stale':
            assert row['error']
            if case['mode'] == 'loader-stale-config':
                assert row['error'] == 'ToolResultPruneConfig: unknown key "maxChars" (allowed: thresholdChars, headChars, tailChars)'
        elif case['recipe'] == 'lifecycle':
            assert row['pending'] and row['retired'] and row['reload'] and row['unloaded']
            assert row['config'] == SMALL
        else:
            assert row['loaded'] and row['unloaded']
            assert row['config'] == dict(thresholdChars=100, headChars=20, tailChars=10)
            assert row['schema'] == dict(type='object', meta=dict(default={}), fields=[
                dict(key=key, type='number', meta=dict(step=1, min=1 if key == 'thresholdChars' else 0, default=value))
                for key, value in DEFAULTS.items()])
        return
    if case['kind'] == 'content':
        assert row['richIdentity']
        config = case.get('config', dict(thresholdChars=code_point_length(PRUNE_MARKER), headChars=0, tailChars=0)
                          if case['recipe'] == 'zero' else SMALL)
        if row['before'] <= config['thresholdChars']:
            assert row['result'] is None
        else:
            assert row['after'] <= config['thresholdChars']
            assert row['after'] < row['before']
            texts = [block['text'] for block in row['result'] if block['type'] == 'text']
            assert ''.join(texts).count(PRUNE_MARKER) == 1
            assert '\ufffd' not in ''.join(texts)
        return
    assert row['messages'] == row['replayMessages']
    assert row['generation'] == row['replayGeneration']
    assert row['events'][4]['data']['message']['content'][0]['content'][0]['text'] == ('A' * (40 if case['recipe'] == 'preserve' else 100))
    if case['recipe'] == 'partial':
        assert row['error'] == 'second replacement rejected'
        assert row['generation'] == 1
        assert row['events'][-1]['type'] == 'compaction/prune'
        return
    assert row['error'] is None
    expected_calls = ['a'] if case['recipe'] in ('preserve', 'invariants') else ['a', 'c']
    assert [entry['callId'] for entry in row['result']['pruned']] == expected_calls
    assert row['result']['charsRemoved'] == sum(entry['charsBefore'] - entry['charsAfter'] for entry in row['result']['pruned'])
    entry = row['result']['pruned'][0]
    assert set(entry) == {'originalSeq', 'replacementSeq', 'callId', 'charsBefore', 'charsAfter'}
    replacement = row['events'][entry['replacementSeq']]
    assert replacement['surfaceOp'] == dict(op='replace', start=entry['originalSeq'], end=entry['originalSeq'])
    assert replacement['sourceEventSeqs'] == [entry['originalSeq']]
    data = replacement['data']
    assert data['error'] == dict(name='ExitError', code='EXIT_1')
    assert data['meta'] == dict(diff=['a', 'b']) and data['futureField'] == dict(nested=True)
    assert data['message']['id'] == 'result-a'
    assert data['message']['content'][0]['isError'] is True
    assert data['message']['futureMessage'] == dict(keep=True)
    assert data['message']['content'][0]['futureBlock'] == dict(keep=True)
    if case['recipe'] != 'snapshot':
        assert row['events'][entry['replacementSeq'] - 1]['data']['shadowedTokenCount'] == row['originalPrice']
        assert row['repeat'] == dict(pruned=[], charsRemoved=0)
        if case['recipe'] == 'invariants':
            assert row['rejection']['addedEvents'] == 1
            assert row['rejection']['generation'] == 0
            assert row['rejection']['beforeTokens'] == row['rejection']['afterTokens']
            assert 'outside any open turn' in row['rejection']['error']
    else:
        # A result appended by the first pricing observer is outside the pass's
        # initial candidate snapshot and must remain unpruned.
        assert row['messages'][-1]['content'][0]['content'][0]['text'] == 'C' * 80


@pytest.mark.parametrize('text, count', [('a😀b', 3), ('a\ud83d\ude00b', 3), ('\ud83dX\ude00', 3), ('e\u0301', 2)])
def test_unicode_code_points(text, count):
    assert code_point_length(text) == count


def test_detached_immutable_configuration_and_native_keyword_adapter():
    raw = dict(thresholdChars=100, headChars=20, tailChars=10)
    pruner = ToolResultPruner(config=raw)
    raw['headChars'] = 1
    assert pruner.config == dict(thresholdChars=100, headChars=20, tailChars=10)
    with pytest.raises(TypeError):
        pruner.config['headChars'] = 1
    with pytest.raises(TypeError):
        DEFAULTS['headChars'] = 1
    assert ToolResultPruner(threshold_chars=100, head_chars=20, tail_chars=10).config == pruner.config
    with pytest.raises(ValueError, match='headChars \\+ marker \\+ tailChars'):
        ToolResultPruner(threshold_chars=20, head_chars=5, tail_chars=5)


def test_rich_order_and_retained_text_fields():
    pruner = ToolResultPruner(config=SMALL)
    original = blocks('rich')
    result = pruner.pruneContent(original)
    assert result == [dict(type='text', text='AAAA' + PRUNE_MARKER, label='first'),
        original[1], original[3], dict(type='text', text='CCC', label='last')]
    assert result[1] is original[1] and result[2] is original[3]


@pytest.mark.asyncio
async def test_real_session_invariants_require_an_open_turn():
    ctx = Context()
    try:
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(InvariantRegistry)
        await ctx.plugin(SessionInvariantPlugin)
        await ctx.plugin(TokenMeterPlugin)
        pruner = ToolResultPruner(config=SMALL, ctx=ctx)
        session = ctx.get('sessions').create('invariants')
        append_step(session, 1, 'a', [dict(type='text', text='A' * 100)])
        before = list(session.events)
        with pytest.raises(Exception, match='outside any open turn'):
            pruner.pruneSession(session)
        # Pricing commits before replacement validation in the source as well.
        # It arms a claim but does not subtract tokens without a replacement.
        assert session.events[:-1] == before and session.surface.replace_generation == 0
        assert session.events[-1]['type'] == 'compaction/prune'
        session.append('turn/start', dict(turn=2))
        assert len(pruner.pruneSession(session)['pruned']) == 1
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_dependency_injection_and_reversible_provider():
    ctx = Context()
    try:
        fiber = await ctx.plugin(ToolResultPrunerPlugin, config=SMALL)
        assert ctx.get('toolResultPruner') is None
        meter = await ctx.plugin(TokenMeterPlugin)
        assert ctx.get('toolResultPruner').config == SMALL
        await meter.dispose()
        assert ctx.get('toolResultPruner') is None
        await ctx.plugin(TokenMeterPlugin)
        assert ctx.get('toolResultPruner').config == SMALL
        await fiber.dispose()
        assert ctx.get('toolResultPruner') is None
        with pytest.raises(ValueError, match='unknown key "maxChars"'):
            await ctx.plugin(ToolResultPrunerPlugin, config=dict(maxChars=100))
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_real_flat_yaml_loader_composition(tmp_path):
    path = tmp_path / 'cordis.yml'
    path.write_text("- name: '@deepseek-ai/dsh-token-meter'\n"
                    "- name: '@deepseek-ai/dsh-compaction-tool-result-pruner'\n"
                    '  config:\n    thresholdChars: 100\n    headChars: 20\n    tailChars: 10\n', encoding='utf-8')
    ctx = Context()
    ctx.baseUrl = tmp_path.as_uri() + '/'
    try:
        await ctx.plugin(Loader)
        loader = ctx.get('loader')
        install_harness_plugin_classes(loader)
        await loader.create(dict(name='cordis:include', config=dict(path=path.as_uri())))
        await loader.await_tasks()
        assert ctx.get('toolResultPruner').config == dict(thresholdChars=100, headChars=20, tailChars=10)
        await loader.root.update([])
        assert ctx.get('toolResultPruner') is None
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_json_roundtrip_retains_pruned_model_messages(tmp_path):
    ctx = Context()
    try:
        TokenMeter(ctx)
        pruner = ToolResultPruner(ctx=ctx, config=SMALL)
        session = Session.create('disk-roundtrip')
        append_step(session, 1, 'a', blocks('astral'))
        session.append('turn/start', dict(turn=2))
        pruner.prune_session(session)
        session.append('turn/end', dict(turn=2, reason=dict(kind='completed')))
        path = tmp_path / 'events.json'
        path.write_text(json.dumps(list(session.events), ensure_ascii=True), encoding='utf-8')
        restored = Session.create(session.id, json.loads(path.read_text(encoding='utf-8')))
        assert restored.derive_messages() == session.derive_messages()
        assert restored.surface.nodes == session.surface.nodes
        assert restored.surface.replace_generation == 1
        with pytest.raises(TypeError):
            session.events[-2]['data']['message']['content'][0]['content'][0]['text'] = 'mutate'
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_direct_service_without_meter_cannot_publish_zero_price():
    ctx = Context()
    try:
        pruner = ToolResultPruner(ctx=ctx, config=SMALL)
        session = Session.create('missing-meter')
        append_step(session, 1, 'a', [dict(type='text', text='A' * 100)])
        before = list(session.events)
        with pytest.raises(AttributeError):
            pruner.prune_session(session)
        assert session.events == before
        assert session.surface.replace_generation == 0
    finally:
        await ctx.fiber.dispose()
