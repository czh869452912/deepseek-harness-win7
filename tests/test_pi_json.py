from dsh.llm.pi_json import dumps, parse_streaming_json
from dsh.llm.pi_replay import arguments


def test_interrupted_tool_arguments_keep_completed_fields_and_partial_strings():
    assert parse_streaming_json(r'{"path":"C:\\work\\new", "content":"hello') == {
        'path': r'C:\work\new', 'content': 'hello'}
    assert parse_streaming_json('{"x":1,"pending":') == {'x': 1}
    assert parse_streaming_json('{"x":[1,{"y":"z') == {'x': [1, {'y': 'z'}]}


def test_invalid_constants_do_not_enter_durable_replay_but_stream_output_is_json():
    assert arguments('{"x":NaN}') == {}
    assert arguments('{"x":Infinity}') == {}
    assert dumps(parse_streaming_json('{"x":Infinity}')) == '{"x":null}'
    assert parse_streaming_json('1,2') == {}
