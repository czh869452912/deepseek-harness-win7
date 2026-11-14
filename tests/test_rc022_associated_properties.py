import asyncio
from scripts import rc022_associated_probe as probe


def test_associated_properties_keep_receiver_and_definition_permissions():
    result = asyncio.run(probe.native())
    expected = ['caller', 'provider', 'extension', [[True, True], [True, True, 'written']], 'own', 'own',
                ['cannot get property "api.secret" without inject'], 'caller-metadata']
    assert result == {'false': expected, 'true': expected}
