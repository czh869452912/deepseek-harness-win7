"""Source-verified literal empty Host halves for browser client discovery."""
import json
from pathlib import Path
from dsh.client.surfaces import _empty_host_half

PURE_HOST_HALVES = {}
for _row in json.loads(Path(__file__).with_name('pure_hosts_current.json').read_text(encoding='utf-8'))['rows']:
    _slug = _row['name'][len('@deepseek-ai/dsh-client-'):]
    _name = ''.join(word.capitalize() for word in _slug.split('-')) + 'Host'
    PURE_HOST_HALVES[_row['name']] = _name
    globals()[_name] = _empty_host_half(
        _name, _row['name'], _row['source'])
