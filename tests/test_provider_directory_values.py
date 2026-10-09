import json
from pathlib import Path
import pytest
from dsh.llm.llm_service import LLMService

ROWS=json.loads((Path(__file__).with_name('fixtures') / 'provider-directory-source-v1.json').read_text(encoding='utf-8'))

@pytest.mark.parametrize('row',ROWS,ids=('omitted','false','true','null','extension'))
def test_public_directory_retains_source_fields_through_replace_and_detachment(row):
    service=LLMService()
    handle=service.register_configurable_providers([row['entry']])
    assert service.listConfigurableProviders()==row['registered']
    assert service.list_configurable_providers()==row['registered']
    handle.replace([dict(row['entry'],settingsPath=['changed'])])
    assert service.listConfigurableProviders()==row['replaced']
    assert service.list_configurable_providers()==row['replaced']
    service.listConfigurableProviders()[0]['settingsPath'].append('external')
    assert service.listConfigurableProviders()==row['afterMutation']
    handle()
    assert service.listConfigurableProviders()==row['disposed']
