import copy

from dsh.llm.pi_completions_params import build_params
from dsh.llm.pi_estimate import estimate_context_tokens


def test_context_capacity_leaves_safety_margin_and_thinking_leaves_answer_budget():
    model = dict(id='m', provider='gateway', api='openai-completions', baseUrl='http://localhost',
                 input=['text'], reasoning=True, contextWindow=8192, maxTokens=8192,
                 compat=dict(supportsThinkingTokenBudget=True, maxTokensField='max_tokens'))
    context = dict(messages=[dict(role='user', content='x' * 400, timestamp=0)])
    before = copy.deepcopy(context)
    params = build_params(model, context, dict(reasoning='high'), simple=True)
    assert params['max_tokens'] == 8192 - 4096 - 100
    assert params['thinking_token_budget'] == params['max_tokens'] - 1024
    assert context == before


def test_anthropic_cache_markers_and_provider_compat_do_not_mutate_context():
    model = dict(id='anthropic/m', provider='openrouter', api='openai-completions',
                 baseUrl='https://openrouter.ai/api/v1', input=['text'], reasoning=False)
    context = dict(systemPrompt='system', messages=[dict(role='user', content='hello', timestamp=0)],
                   tools=[dict(name='run', description='Run', parameters=dict(type='object'))])
    before = copy.deepcopy(context)
    result = build_params(model, context, dict(cacheRetention='long'))
    assert result['messages'][0]['content'][0]['cache_control']['ttl'] == '1h'
    assert result['messages'][-1]['content'][0]['cache_control']['ttl'] == '1h'
    assert result['tools'][-1]['cache_control']['ttl'] == '1h'
    assert context == before


def test_estimate_uses_valid_usage_then_counts_only_trailing_content():
    usage = dict(totalTokens=200, input=190, output=10, cacheRead=0, cacheWrite=0)
    history = [dict(role='user', content='earlier', timestamp=0),
               dict(role='assistant', content=[], usage=usage, stopReason='stop', timestamp=1),
               dict(role='user', content='abcd', timestamp=2)]
    result = estimate_context_tokens(dict(systemPrompt='already counted', messages=history))
    assert result == dict(tokens=201, usageTokens=200, trailingTokens=1, lastUsageIndex=1)
