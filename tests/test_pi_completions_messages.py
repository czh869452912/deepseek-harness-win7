from dsh.llm.pi_completions_messages import convert_messages, normalize_id, sanitize


def test_response_item_ids_stay_distinct_and_tool_results_follow_rewritten_ids():
    model = dict(provider='openai', api='openai-completions', id='next', input=['text'])
    ids = ['call|' + 'item' * 100 + suffix for suffix in ('a', 'b')]
    normalized = [normalize_id(identity, model) for identity in ids]
    assert len(set(normalized)) == 2 and all(len(identity) <= 40 for identity in normalized)
    calls = [dict(type='toolCall', id=identity, name='run', arguments={}) for identity in ids]
    history = [dict(role='assistant', provider='old', api='openai-responses', model='old', content=calls, stopReason='toolUse')]
    history.extend(dict(role='toolResult', toolCallId=identity, toolName='run', content=[dict(type='text', text='ok')]) for identity in ids)
    wire = convert_messages(model, dict(messages=history), {})
    assert [call['id'] for call in wire[0]['tool_calls']] == normalized
    assert [row['tool_call_id'] for row in wire[1:]] == normalized


def test_tool_images_follow_all_results_and_unicode_surrogates_do_not_reach_json():
    model = dict(provider='custom', api='openai-completions', id='m', input=['text', 'image'])
    image = dict(type='image', mimeType='image/png', data='YWJj')
    results = [dict(role='toolResult', toolCallId=str(index), toolName='read', content=[image]) for index in range(2)]
    wire = convert_messages(model, dict(messages=results), dict(requiresAssistantAfterToolResult=True))
    assert [row['role'] for row in wire] == ['tool', 'tool', 'assistant', 'user']
    assert len(wire[-1]['content']) == 3
    assert sanitize('a\ud800b\ud83d\ude00\udc00') == 'ab😀'
