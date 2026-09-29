import copy

from dsh.llm.pi_transform import transform_messages


def test_foreign_resume_strips_signatures_and_repairs_tool_flow_without_mutation():
    model = dict(provider='target', api='openai-completions', id='new', input=['text'])
    history = [dict(role='assistant', provider='old', api='anthropic-messages', model='old', stopReason='toolUse',
                    content=[dict(type='thinking', thinking='', redacted=True, thinkingSignature='secret'),
                             dict(type='thinking', thinking='reason', thinkingSignature='native'),
                             dict(type='toolCall', id='a|item', name='run', arguments={}, thoughtSignature='native'),
                             dict(type='toolCall', id='missing', name='other', arguments={})]),
               dict(role='toolResult', toolCallId='a|item', toolName='run', content=[dict(type='text', text='ok')]),
               dict(role='user', content='continue')]
    before = copy.deepcopy(history)
    result = transform_messages(history, model, lambda identity, *_: identity.replace('|', '_'), now=lambda: 123)
    assert result[0]['content'][0] == dict(type='text', text='reason')
    assert 'thoughtSignature' not in result[0]['content'][1]
    assert result[0]['content'][1]['id'] == result[1]['toolCallId'] == 'a_item'
    assert result[2]['toolCallId'] == 'missing' and result[2]['isError'] is True
    assert result[2]['timestamp'] == 123
    assert result[-1] == history[-1]
    assert history == before


def test_same_model_keeps_opaque_reasoning_but_aborted_turn_is_not_replayed():
    model = dict(provider='same', api='anthropic-messages', id='same', input=['text'])
    assistant = dict(role='assistant', provider='same', api=model['api'], model='same', stopReason='stop',
                     content=[dict(type='thinking', thinking='', redacted=True, thinkingSignature='opaque')])
    assert transform_messages([assistant], model) == [assistant]
    assert transform_messages([dict(assistant, stopReason='aborted')], model) == []
