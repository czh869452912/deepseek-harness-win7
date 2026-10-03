import copy

import pytest

from scripts.acp_mcp_oracle import expected_runtime, validate_declarations, validate_runtime


def declarations():
    return [{'servers': [{'name': 'controlled-%s' % index, 'command': 'C:/controlled.exe', 'args': [], 'env': []}],
        'cwd': 'C:/workspace', 'result': {'data': [{'transport': 'stdio', 'serverName': 'controlled-%s' % index,
            'command': 'C:/controlled.exe', 'args': [], 'env': {}, 'cwd': 'C:/workspace',
            'toolCallTimeoutMs': 60000, 'failOnStartupError': True,
            'reconnect': {'enabled': True, 'initialDelayMs': 500, 'maxDelayMs': 30000, 'maxAttempts': 10}}]}}
        for index in range(58)]


def test_complete_declared_acp_mcp_observations_are_admitted():
    validate_runtime(expected_runtime())
    validate_declarations(declarations())


@pytest.mark.parametrize('field', list(expected_runtime()))
@pytest.mark.parametrize('damage', ['missing', 'false', 'foreign'])
def test_runtime_predicate_rejects_missing_false_or_foreign_observations(field, damage):
    observed = copy.deepcopy(expected_runtime())
    if damage == 'missing':
        del observed[field]
    else:
        observed[field] = False if damage == 'false' else {'foreign': True}
    with pytest.raises(ValueError):
        validate_runtime(observed)


@pytest.mark.parametrize('field', ['firstResult', 'siblingResult', 'resumedResult'])
@pytest.mark.parametrize('damage', ['numeric-error', 'missing-value', 'changed-value', 'changed-content'])
def test_actual_runtime_consumer_cannot_be_invented_or_weakly_typed(field, damage):
    observed = copy.deepcopy(expected_runtime())
    if damage == 'numeric-error':
        observed[field]['isError'] = 0
    elif damage == 'missing-value':
        del observed[field]['value']
    elif damage == 'changed-value':
        observed[field]['value']['structuredContent']['explicit'] = 'foreign'
    else:
        observed[field]['content'][0]['text'] = 'invented'
    with pytest.raises(ValueError):
        validate_runtime(observed)


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'empty-success', 'numeric-startup',
    'missing-name', 'missing-timeout', 'numeric-reconnect', 'partial-error', 'mounted-error'])
def test_declaration_predicate_rejects_partial_or_fake_success(damage):
    rows = declarations()
    if damage == 'missing':
        rows.pop()
    elif damage == 'duplicate':
        rows[1] = copy.deepcopy(rows[0])
    elif damage == 'empty-success':
        rows[0]['result']['data'] = []
    elif damage == 'numeric-startup':
        rows[0]['result']['data'][0]['failOnStartupError'] = 1
    elif damage == 'missing-name':
        del rows[0]['result']['data'][0]['serverName']
    elif damage == 'missing-timeout':
        del rows[0]['result']['data'][0]['toolCallTimeoutMs']
    elif damage == 'numeric-reconnect':
        rows[0]['result']['data'][0]['reconnect']['enabled'] = 1
    elif damage == 'partial-error':
        rows[0]['result'] = {'message': 'mcpServers failed'}
    else:
        rows[0]['result'] = {'name': 'AcpMcpConfigError', 'message': 'mcpServers failed', 'mounted': [{}]}
    with pytest.raises(ValueError):
        validate_declarations(rows)
