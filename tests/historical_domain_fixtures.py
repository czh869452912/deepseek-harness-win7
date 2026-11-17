"""Historical domain regressions, with original Source identities preserved.

These checks exercise retained Native compatibility helpers. Current production
contracts must pass their separate rc022 Source/native lanes.
"""
from evidence_fixtures import read_member
from release_gate_fixtures import native_fixture


ARCHIVE = 'RC3-QUALIFICATION-20261018-228CFACC.zip'
PERMISSION_MEMBER = 'full-gate-root.zip!/permission-presets-paired.source.json'


def permission_source():
    return read_member(ARCHIVE, PERMISSION_MEMBER)


def permission_identity(source):
    from scripts.permission_presets_oracle import identity
    # Validate the complete original manifest against its byte-preserved member,
    # rather than compare old Source paths with the current Source checkout.
    if not isinstance(source, dict) or source.get('inputs') != permission_source()['inputs']:
        raise ValueError('Historical permission Source guarded bytes differ')
    return identity(source, None, check_files=False)


def permission_pair():
    # No descriptor rebinding or synthetic Source values: original Source facts
    # are compared with a newly executed retained Native domain provider.
    return permission_source(), native_fixture('permission-presets')
