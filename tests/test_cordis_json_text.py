import pytest

from dsh.cordis.json_text import stringify_json


@pytest.mark.parametrize(('value', 'expected'), [
    ({'label': '会话😀', 'items': [None, True, False, -1, 9007199254740992],
      'empty': {}, 'escape': '\n\x00"\\'},
     '{"label":"会话😀","items":[null,true,false,-1,9007199254740992],"empty":{},"escape":"\\n\\u0000\\"\\\\"}'),
    ({'rows': [{'10': 10, '01': 1, '2': 2, 'name': 'x', '4294967295': 0}]},
     '{"rows":[{"2":2,"10":10,"01":1,"name":"x","4294967295":0}]}'),
    ([1.0, -0.0, 1e-7, 1e20, 9007199254740993, float('nan'), float('inf')],
     '[1,0,1e-7,100000000000000000000,9007199254740992,null,null]'),
    ({'\ud83d\ude00': 'older', '😀': '\ud800', 'end': '\udc00'},
     '{"😀":"\\ud800","end":"\\udc00"}'),
])
def test_json_text_preserves_ecmascript_bytes(value, expected):
    assert stringify_json(value).encode('utf-8') == expected.encode('utf-8')


def test_json_text_rejects_non_json_types():
    with pytest.raises(TypeError, match='plain JSON'):
        stringify_json({'items': [b'raw']})
    with pytest.raises(TypeError, match='string keys'):
        stringify_json({'nested': {1: 'number key'}})
