import copy

import pytest

from dsh.llm.message import create_user_message, freeze_message


@pytest.mark.parametrize('repeat', (False, True))
def test_detached_message_keeps_aliases_and_dictionary_and_list_cycles(repeat):
    shared = dict(items=[])
    original = dict(id='preserved', extra=dict(first=shared, second=shared))
    original['extra']['self'] = original['extra']
    shared['items'].extend([shared['items'], original])
    snapshot = freeze_message(original)
    if repeat:
        snapshot = freeze_message(snapshot)
    assert snapshot is not original
    assert snapshot['id'] == 'preserved'
    assert snapshot['extra']['first'] is snapshot['extra']['second']
    assert snapshot['extra']['self'] is snapshot['extra']
    items = snapshot['extra']['first']['items']
    assert items[0] is items
    assert items[1] is snapshot
    detached = copy.deepcopy(snapshot)
    assert detached is not snapshot
    assert detached['extra']['first']['items'][1] is detached
    detached['extra']['first']['items'].append('mutable clone')
    assert len(items) == 2


@pytest.mark.parametrize('mutation', ('root-set', 'root-delete', 'root-update', 'root-pop',
    'source-set', 'content-set', 'content-append', 'content-clear', 'block-update'))
def test_identified_message_rejects_nested_mutation(mutation):
    message = create_user_message(dict(content=[dict(type='text', text='retained')], source=dict(kind='user')))
    original = copy.deepcopy(message)
    actions = {
        'root-set': lambda: message.__setitem__('id', 'changed'),
        'root-delete': lambda: message.__delitem__('id'),
        'root-update': lambda: message.update(id='changed'),
        'root-pop': lambda: message.pop('id'),
        'source-set': lambda: message['source'].__setitem__('kind', 'changed'),
        'content-set': lambda: message['content'].__setitem__(0, {}),
        'content-append': lambda: message['content'].append({}),
        'content-clear': lambda: message['content'].clear(),
        'block-update': lambda: message['content'][0].update(text='changed'),
    }
    with pytest.raises(TypeError):
        actions[mutation]()
    assert message == original
