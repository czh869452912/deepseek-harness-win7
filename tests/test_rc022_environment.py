import asyncio
from scripts import rc022_environment_probe as probe


def test_route_names_validate_all_layers_before_materializing(tmp_path):
    probe.OUTPUT = tmp_path
    rows = asyncio.run(probe.native())
    assert len(rows) == 48
    for row in rows:
        accepted = row['name'] in probe.NAMES[:7] and row['mode'] != 'project'
        assert (row['error'] is None) == accepted
        if accepted:
            assert row['value'] == ('inherited' if row['mode'] == 'inherited' else 'route')
            assert row['entry']['source'] == {'same': 'project-env', 'inherited': 'process'}.get(row['mode'], 'user-env')
        else:
            assert row['ordinary'] is None
            if row['name'] in probe.NAMES[7:9]:
                assert 'spell it '+row['name'].upper() in row['error']
