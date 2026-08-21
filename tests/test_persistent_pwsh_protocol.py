import sys
import pytest
from dsh.shell.terminal import PersistentTerminal, quote_for_pwsh


def test_quote_for_pwsh():
    raw = 'echo "hello $world" `test`\nline2'
    escaped = quote_for_pwsh(raw)
    assert '`"' in escaped
    assert '`$' in escaped
    assert '``' in escaped
    assert '`n' in escaped


def test_persistent_terminal_state():
    term = PersistentTerminal(shell_type="auto")
    if term.shell_type == "powershell":
        code1, out1, _ = term.execute("$foo_persistent_val = 98765")
        assert code1 == 0
        code2, out2, _ = term.execute('Write-Output "VAL:$foo_persistent_val"')
        assert code2 == 0
        assert "VAL:98765" in out2
    else:
        code1, out1, _ = term.execute("export FOO_PERSISTENT=98765")
        assert code1 == 0
        code2, out2, _ = term.execute('echo "VAL:$FOO_PERSISTENT"')
        assert code2 == 0
        assert "VAL:98765" in out2
    term.reset()
