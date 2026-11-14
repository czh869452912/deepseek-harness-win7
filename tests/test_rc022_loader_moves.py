"""Persisted ownership must follow moved entries, including group members."""
import asyncio
from scripts import rc022_loader_move_probe as probe


def test_two_file_moves_preflight_and_explicit_positions(tmp_path):
    probe.OUTPUT=tmp_path
    observed=asyncio.run(probe.native())
    for mode in probe.MODES:
        result=observed[mode]
        assert result['same_entry'] and result['same_member']
        assert result['same_fiber']
    assert observed['leaf']['files']==[[],[probe.group('g',[probe.row('a',2)])]]
    assert observed['leaf']['entry_id']=='R:a'
    assert observed['group']['stores']==[[],['a','g','inner','outer']]
    assert observed['group']['group_owner'] is True
    assert observed['group']['calls']==[1]
    assert observed['group']['removed']==[['g'],[probe.group('g',[])],True]
    for mode in ('collision','member-collision'):
        assert observed[mode]['error']=='entry a already exists in the target tree'
        assert observed[mode]['entry_id'].startswith('L:')
    # The two parent moves cancel in one journal batch; same-parent reorder is not persisted by Source.
    assert observed['same-tree']['files'][0]==[probe.row('a'),probe.row('b'),probe.group('g',[])]
    assert observed['positions']['files'][0]==[probe.row('a'),probe.row('b'),probe.group('g',[probe.row('c')])]
    assert observed['disabled']['files'][0]==[]
    assert observed['disabled']['files'][1][0]['config'][0]['disabled'] is True
