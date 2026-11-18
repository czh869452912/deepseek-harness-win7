"""A broken shared observer must fail every consumer without rerunning its job."""
import pytest

from release_gate_fixtures import runtime_fixture


def test_shared_observer_failure_preserves_cause_without_repeating_io(tmp_path):
    attempts = tmp_path / 'attempts.txt'
    primary = ValueError('original observer diagnostic')

    @runtime_fixture
    def failing_observer():
        with attempts.open('a', encoding='utf-8') as stream:
            stream.write('executed\n')
        raise primary

    with pytest.raises(ValueError) as first:
        failing_observer()
    assert first.value is primary
    for _ in range(3):
        with pytest.raises(RuntimeError, match='failing_observer') as repeated:
            failing_observer()
        assert repeated.value.__cause__ is primary
    assert attempts.read_text(encoding='utf-8') == 'executed\n'


def test_shared_observer_success_retains_the_same_complete_result():
    calls = []
    result = {'source': [1, 2], 'native': [1, 2]}

    @runtime_fixture
    def successful_observer():
        calls.append('executed')
        return result

    assert successful_observer() is result
    assert successful_observer() is result
    assert calls == ['executed']
