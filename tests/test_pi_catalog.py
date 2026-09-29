import copy

import pytest

from dsh.llm.pi_catalog import catalog_models, catalog_provider_ids
from dsh.llm.pi_config import resolve_profiles


def test_catalog_caps_are_not_implicit_request_limits_and_results_are_detached():
    assert 'openai' in catalog_provider_ids()
    models = catalog_models('openai')
    identity = next(iter(models))
    config = {'openai': {'models': [{'id': identity}]}}
    first = resolve_profiles(config)['openai']
    assert first['configuredMaxTokens'] == {}
    assert first['models'][0]['maxTokens'] == models[identity]['maxTokens']
    first['models'][0]['input'].clear()
    assert resolve_profiles(config)['openai']['models'][0]['input']
    config['openai']['models'][0]['maxTokens'] = 123
    assert resolve_profiles(config)['openai']['configuredMaxTokens'] == {identity: 123}


def test_catalog_override_preserves_other_models_and_rejects_typos():
    models = catalog_models('deepseek')
    identity = next(iter(models))
    config = {'deepseek': {'modelOverrides': {identity: {'contextWindow': 99}}}}
    result = resolve_profiles(config)['deepseek']['models']
    assert len(result) == len(models)
    assert next(model for model in result if model['id'] == identity)['contextWindow'] == 99
    for patch in ({'missing': {}}, {identity: {'id': 'renamed'}}):
        with pytest.raises(ValueError):
            resolve_profiles({'deepseek': {'modelOverrides': patch}})


def test_declared_reasoning_and_protocol_compat_are_explicit():
    config = {'gateway': {'api': 'openai-completions', 'baseURL': 'http://localhost',
                         'compat': {'supportsStore': False},
                         'models': [{'id': 'm', 'reasoningEfforts': {'off': None, 'high': 'deep'}}]}}
    before = copy.deepcopy(config)
    model = resolve_profiles(config)['gateway']['models'][0]
    assert model['thinkingLevelMap']['high'] == 'deep'
    assert model['thinkingLevelMap']['low'] is None
    assert 'off' not in model['thinkingLevelMap']
    assert model['compat'] == {'supportsStore': False}
    assert config == before
    config['gateway']['models'][0]['compat'] = {'supportsTemperature': False}
    with pytest.raises(ValueError):
        resolve_profiles(config)
