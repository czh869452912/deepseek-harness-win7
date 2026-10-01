"""Python Host schema contribution from the same contract used by the Client."""
import json
import os
from dsh.plugin_api import JsonSchemaCodec

with open(os.path.join(os.path.dirname(__file__), 'contract.json'), encoding='utf-8') as stream:
    TYPERT = json.load(stream)
for invocation in TYPERT['invocations']:
    for descriptor in invocation['parameters'] + [dict(codec=invocation['result'])]:
        codec = descriptor['codec']
        codec['schema'] = JsonSchemaCodec(codec['schema'])
