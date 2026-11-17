"""Installed application evidence must bind actual browser and candidate bytes."""
import pytest
from scripts.current_application_gate import digest, validate_observations


@pytest.mark.parametrize('damage', [None, 'root', 'python', 'executable', 'closure', 'native-bytes',
                                   'candidate-bytes', 'module-escape', 'browser', 'mux', 'console', 'response'])
def test_installed_application_observations_refuse_unqualified_runtime_or_browser(tmp_path, damage):
    candidate, portable = tmp_path / 'candidate', tmp_path / 'portable'
    modules = {}
    for name in ['dsh/boot/profile_boot.py', 'dsh/typert/gateway_authorized.py',
                 'dsh/schedule/service_current.py', 'dsh/host/browser_compat/plugin.py',
                 'dsh/boot/plugin_market_022.py']:
        for root in [candidate, portable]:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# selected module\n', encoding='utf-8')
        modules[name] = digest(portable / name)
    observed = dict(passed=True, kind='market', modules=modules, runtime=dict(root=str(portable),
        executable=str(portable / 'python.exe'), python='3.8.10 actual runtime'))
    browser = dict(passed=True, remoteMux=True, errors=[], responses=[])
    if damage == 'root': observed['runtime']['root'] = str(candidate)
    if damage == 'python': observed['runtime']['python'] = '3.11.0'
    if damage == 'executable': observed['runtime']['executable'] = str(candidate / 'python.exe')
    if damage == 'closure': modules.pop('dsh/boot/plugin_market_022.py')
    if damage in ['native-bytes', 'candidate-bytes']:
        root = portable if damage == 'native-bytes' else candidate
        (root / 'dsh/boot/profile_boot.py').write_text('# different\n', encoding='utf-8')
    if damage == 'module-escape': modules['../foreign.py'] = '0' * 64
    if damage == 'browser': browser['passed'] = False
    if damage == 'mux': browser['remoteMux'] = False
    if damage == 'console': browser['errors'] = ['failure']
    if damage == 'response': browser['responses'] = [dict(status=500)]
    if damage is None:
        validate_observations(observed, browser, portable, candidate)
    else:
        with pytest.raises(ValueError): validate_observations(observed, browser, portable, candidate)
