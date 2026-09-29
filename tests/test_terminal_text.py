from dsh.terminal.text import TerminalSanitizer, BoundedTextBuffer, utf8_tail


def test_split_escapes_prompt_tail_and_crlf_carry():
    sanitizer = TerminalSanitizer(64)
    assert sanitizer.push('before\x1b[') == dict(text='before', prompt=False)
    assert sanitizer.push('31mred\x1b]133;D;') == dict(text='red', prompt=False)
    assert sanitizer.push('0\x07dsh') == dict(text='dsh', prompt=True, promptTail='dsh')
    assert sanitizer.push('> \r') == dict(text='> ', prompt=False, promptTail='> \r')
    assert sanitizer.push('\nnext') == dict(text='\nnext', prompt=False, promptTail='\nnext')
    assert sanitizer.push('\r')['text'] == ''
    assert sanitizer.flush() == '\n'


def test_oversized_control_payload_stays_discarded_through_split_terminator():
    sanitizer = TerminalSanitizer(16)
    assert sanitizer.push('\x1b]133;D;' + 'x' * 1000) == dict(text='', prompt=False)
    assert sanitizer.pending == ''
    assert sanitizer.push('hostile\x1b') == dict(text='', prompt=False)
    assert sanitizer.push('\\safe') == dict(text='safe', prompt=False)
    assert sanitizer.push('\x1b[' + '1;' * 1000) == dict(text='', prompt=False)
    assert sanitizer.push('msafe') == dict(text='safe', prompt=False)


def test_utf8_byte_and_line_bounds_with_incremental_consumption():
    assert utf8_tail('前中文', 7) == ('中文', True)
    buffer = BoundedTextBuffer(10, 2)
    buffer.append('old\nfirst\n中文')
    assert buffer.snapshot() == dict(text='rst\n中文', truncated=True)
    assert buffer.consume() == dict(delta='rst\n中文', truncated=True)
    assert buffer.snapshot() == dict(text='', truncated=False)
