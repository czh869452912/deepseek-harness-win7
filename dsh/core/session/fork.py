"""Exact inclusive fork prefixes, inherited cuts and synthetic open-tail closers."""
from dsh.core.session.repair import open_turn_closers


def build_fork_seed(events, boundary):
    boundary = int(boundary)
    prefix = list(events[:boundary + 1])
    prefix.append(dict(type='session/end-seed', seq=boundary + 1,
                       time=events[boundary]['time'], data=dict(inherited=True)))
    return prefix + open_turn_closers(prefix, dict(kind='forked'))


buildForkSeed = build_fork_seed
