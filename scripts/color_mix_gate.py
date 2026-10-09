"""Literal CSSOM and reversible owner checks for actual browser receipts.

The modern browser serialization and fixed 108 serialization are checked
separately. This covers the pinned bundled sRGB expressions and controlled
style/inheritance/media/lifecycle scenarios, not arbitrary CSS or equal pixels.
"""
import copy

transparent = "rgba(0, 0, 0, 0)"
states=['initial','ancestor-change','local-removal','style-replaced-without-mix','style-mix-restored','style-unmounted']
legacy_a=['rgba(80, 120, 160, 0.25)','rgba(40, 60, 80, 0.25)','rgba(40, 60, 80, 0.25)','rgb(11, 22, 33)','rgba(40, 60, 80, 0.25)','rgba(0, 0, 0, 0)']
legacy_b=['rgba(160, 80, 40, 0.25)','rgba(160, 80, 40, 0.25)']+legacy_a[2:]
modern_a=['color(srgb 0.313726 0.470588 0.627451 / 0.25)','color(srgb 0.156863 0.235294 0.313726 / 0.25)','color(srgb 0.156863 0.235294 0.313726 / 0.25)','rgb(11, 22, 33)','color(srgb 0.156863 0.235294 0.313726 / 0.25)','rgba(0, 0, 0, 0)']
modern_b=['color(srgb 0.627451 0.313726 0.156863 / 0.25)']*2+modern_a[2:]

def _validate_phase(phase, legacy):
    a, b = (legacy_a, legacy_b) if legacy else (modern_a, modern_b)
    themes = (['rgba(255, 255, 255, 0.6)', 'rgba(21, 21, 23, 0.6)', 'rgba(255, 255, 255, 0.6)']
              if legacy else ['color(srgb 1 1 1 / 0.6)', 'color(srgb 0.0823529 0.0823529 0.0901961 / 0.6)', 'color(srgb 1 1 1 / 0.6)'])
    if not (phase['passed'] is True and phase['hostErrors'] == ''):
        raise ValueError("CSS color-mix receipt differs: phase['passed'] is True and phase['hostErrors'] == ''")
    if not (isinstance(phase['browserErrors'], str)):
        raise ValueError("CSS color-mix receipt differs: isinstance(phase['browserErrors'], str)")
    dynamic = phase['cssMixDynamic']
    if not (dynamic['immutable'] is True):
        raise ValueError("CSS color-mix receipt differs: dynamic['immutable'] is True")
    if not (dynamic['values'] == [dict(phase=n, a=x, b=y) for n, x, y in zip(states, a, b)]):
        raise ValueError("CSS color-mix receipt differs: dynamic['values'] == [dict(phase=n, a=x, b=y) for n, x, y in zip(states, a, b)]")
    if not (dynamic['themes'] == [dict(phase=n, dark=d, base=c, paint=p) for n, d, c, p in zip(
        ['initial', 'theme-toggled', 'theme-restored'], [False, True, False], ['#fff', '#151517', '#fff'], themes)]):
        raise ValueError("CSS color-mix receipt differs: dynamic['themes'] == [dict(phase=n, dark=d, base=c, paint=p) for n, d, c, p in zip(")
    own = dynamic['ownedProperty']
    if not (own['remainingOwnProperties'] == []):
        raise ValueError("CSS color-mix receipt differs: own['remainingOwnProperties'] == []")
    if legacy:
        if not (own['generatedName'].startswith('--dsh-host-mix-')):
            raise ValueError("CSS color-mix receipt differs: own['generatedName'].startswith('--dsh-host-mix-')")
        if not (own['beforeRemoval'] == 'rgba(40,60,80,0.25)' and own['afterRemoval'] == ''):
            raise ValueError("CSS color-mix receipt differs: own['beforeRemoval'] == 'rgba(40,60,80,0.25)' and own['afterRemoval'] == ''")
        for facts in [phase['cssMixAdapter'], dynamic['adapter']]:
            if not (facts['errors'] == [] and facts['disposed'] is False):
                raise ValueError("CSS color-mix receipt differs: facts['errors'] == [] and facts['disposed'] is False")
    else:
        if not (dynamic['adapter'] is None and own['generatedName'] is None):
            raise ValueError("CSS color-mix receipt differs: dynamic['adapter'] is None and own['generatedName'] is None")
    lifecycle = phase['cssLifecycle']
    if not (lifecycle['managerPresent'] is legacy and lifecycle['active'] is legacy):
        raise ValueError("CSS color-mix receipt differs: lifecycle['managerPresent'] is legacy and lifecycle['active'] is legacy")
    if not (lifecycle['originalImmutable'] is True):
        raise ValueError("CSS color-mix receipt differs: lifecycle['originalImmutable'] is True")
    paints = [a[0], transparent, a[0], transparent, a[0], transparent if legacy else a[0], a[0], a[0]]
    if not (lifecycle['rows'] == [dict(phase=n, paint=p) for n, p in zip(
        ['active', 'media-disabled', 'media-restored', 'sheet-disabled', 'sheet-restored', 'disposed', 'reinstalled', 'reinstalled-twice'], paints)]):
        raise ValueError("CSS color-mix receipt differs: lifecycle['rows'] == [dict(phase=n, paint=p) for n, p in zip(")
    removed = lifecycle['removed']
    if not (removed['symbolAbsent'] is True and removed['clones'] == 0 and removed['inline'] == []):
        raise ValueError("CSS color-mix receipt differs: removed['symbolAbsent'] is True and removed['clones'] == 0 and removed['inline'] == []")
    if not (lifecycle['preserved'] == dict(value='original-owner-value', priority='important')):
        raise ValueError("CSS color-mix receipt differs: lifecycle['preserved'] == dict(value='original-owner-value', priority='important')")
    if legacy:
        if not (lifecycle['clonesBefore'] == lifecycle['clonesAfter'] and lifecycle['clonesBefore'] > 0):
            raise ValueError("CSS color-mix receipt differs: lifecycle['clonesBefore'] == lifecycle['clonesAfter'] and lifecycle['clonesBefore'] > 0")
        if not (removed['facts']['disposed'] is True and removed['facts']['activeStyles'] == 0):
            raise ValueError("CSS color-mix receipt differs: removed['facts']['disposed'] is True and removed['facts']['activeStyles'] == 0")
        if not (removed['facts']['errors'] == [] and lifecycle['final']['errors'] == []):
            raise ValueError("CSS color-mix receipt differs: removed['facts']['errors'] == [] and lifecycle['final']['errors'] == []")
        if not (lifecycle['beforeMutation'] == lifecycle['afterMutation']):
            raise ValueError("CSS color-mix receipt differs: lifecycle['beforeMutation'] == lifecycle['afterMutation']")
        if not (lifecycle['replacedOwnerDisposed'] is True):
            raise ValueError("CSS color-mix receipt differs: lifecycle['replacedOwnerDisposed'] is True")
    else:
        if not (lifecycle['clonesBefore'] == lifecycle['clonesAfter'] == 0):
            raise ValueError("CSS color-mix receipt differs: lifecycle['clonesBefore'] == lifecycle['clonesAfter'] == 0")
        if not (removed['facts'] is None and lifecycle['final'] is None):
            raise ValueError("CSS color-mix receipt differs: removed['facts'] is None and lifecycle['final'] is None")
    invalid = phase['cssInvalidValue']
    if not (invalid['fallback'] == a[0] and invalid['cyclic'] == transparent and invalid['inherited'] == a[1]):
        raise ValueError("CSS color-mix receipt differs: invalid['fallback'] == a[0] and invalid['cyclic'] == transparent and invalid['inherited'] == a[1]")
    if not (invalid['errors'] == []):
        raise ValueError("CSS color-mix receipt differs: invalid['errors'] == []")
    if legacy:
        if not (invalid['facts']['errors'] == []):
            raise ValueError("CSS color-mix receipt differs: invalid['facts']['errors'] == []")
    else:
        if not (invalid['facts'] is None):
            raise ValueError("CSS color-mix receipt differs: invalid['facts'] is None")
    listeners = phase['cssListenerOwnership']
    if not (listeners['active'] is legacy and listeners['before'] == listeners['restored']):
        raise ValueError("CSS color-mix receipt differs: listeners['active'] is legacy and listeners['before'] == listeners['restored']")
    expected = copy.deepcopy(listeners['before'])
    if legacy:
        for target, names in [('window', ['resize', 'beforeprint', 'afterprint', 'pagehide', 'pageshow']),
                              ('document', ['pointerover', 'pointerout', 'focusin', 'focusout'])]:
            for name in names:
                if not (expected[target][name] >= 1):
                    raise ValueError('CSS color-mix receipt differs: expected[target][name] >= 1')
                expected[target][name] -= 1
                if expected[target][name] == 0:
                    del expected[target][name]
    if not (listeners['removed'] == expected):
        raise ValueError("CSS color-mix receipt differs: listeners['removed'] == expected")
    if not (phase['cssMediaConditions'] == [dict(media=n, paint=p, variable=c) for n, p, c in zip(
        ['screen', 'print', 'screen'], [a[0], a[1], a[0]], ['rgb(80,120,160)', 'rgb(40,60,80)', 'rgb(80,120,160)'])]):
        raise ValueError("CSS color-mix receipt differs: phase['cssMediaConditions'] == [dict(media=n, paint=p, variable=c) for n, p, c in zip(")


def validate_phase(phase, legacy):
    try:
        _validate_phase(phase, legacy)
    except (KeyError, TypeError, IndexError, AttributeError) as error:
        raise ValueError('CSS color-mix receipt is incomplete or malformed') from error
