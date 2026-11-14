from scripts.rc022_hmr_plan_probe import cases, observe


def test_replacement_plans_preserve_unmanaged_host_and_child_ownership(tmp_path):
    rows = observe(tmp_path/'observations', cases())
    by_name = {row['mode']:row for row in rows}
    assert len(rows) == 360
    assert by_name['managed']['evicted'] == [0, 1]
    assert by_name['child']['evicted'] == [0, 1]
    assert by_name['child']['fibers'] == ['1:0', '0:0', '0:1']
    for mode in ('unmanaged', 'unaffected-parent', 'stale-wrapper', 'unlisted'):
        assert by_name[mode]['pending'] == [dict(node=0, reason='unmanaged-plugin')]
        assert by_name[mode]['evicted'] == []
    assert by_name['host']['pending'] == [dict(node=0, reason='host-module')]
    assert by_name['empty']['evicted'] == [0, 1]
    assert by_name['cycle']['evicted'] == [0, 1, 2]
