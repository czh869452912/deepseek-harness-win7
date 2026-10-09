"""Real captured CSSOM facts and refusal controls, independent of renderer code."""
import copy
import json
from pathlib import Path

import pytest

from scripts.color_mix_gate import validate_phase


def observations():
    return json.loads((Path(__file__).with_name('fixtures') / 'color_mix_browser_values.json').read_text(encoding='utf-8'))['observers']


@pytest.mark.parametrize('browser', ['native108', 'modern'])
def test_captured_original_browser_css_lifetimes(browser):
    for phase in observations()[browser]['phases']:
        validate_phase(phase, legacy=browser == 'native108')


@pytest.mark.parametrize('browser', ['native108', 'modern'])
@pytest.mark.parametrize('damage', ['missing', 'paint', 'theme', 'original', 'listener', 'media', 'retained-inline',
                                   'parser', 'native-invasion', 'prior-owner'])
def test_css_qualification_refuses_incomplete_or_changed_observations(browser, damage):
    phase = copy.deepcopy(observations()[browser]['phases'][0])
    if damage == 'missing': phase.pop('cssLifecycle')
    elif damage == 'paint': phase['cssMixDynamic']['values'][0]['a'] = 'rgba(0, 0, 0, 0)'
    elif damage == 'theme': phase['cssMixDynamic']['themes'][1]['dark'] = False
    elif damage == 'original': phase['cssLifecycle']['originalImmutable'] = False
    elif damage == 'listener': phase['cssListenerOwnership']['removed']['window']['resize'] += 1
    elif damage == 'media': phase['cssMediaConditions'][1]['paint'] = 'rgba(0, 0, 0, 0)'
    elif damage == 'retained-inline': phase['cssLifecycle']['removed']['inline'].append('--dsh-host-mix-0')
    elif damage == 'parser': phase['cssInvalidValue']['errors'].append('unsupported syntax')
    elif damage == 'native-invasion': phase['cssLifecycle']['managerPresent'] = browser == 'modern'
    elif damage == 'prior-owner': phase['cssLifecycle']['preserved']['priority'] = ''
    with pytest.raises(ValueError, match='CSS color-mix'):
        validate_phase(phase, legacy=browser == 'native108')
