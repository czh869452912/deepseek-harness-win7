"""Connection-owned default SDK response cache, with invalidation generations."""
import json
import time

from dsh.cordis.json_text import stringify_json


class CurrentResponseCache:
    def __init__(self):
        self.entries = {}
        self.generations = {}
        self.now = lambda: time.time() * 1000

    def capture(self, method, params=''):
        return self.generations.setdefault((method, params), 0)

    def evict(self, method, params=''):
        key = (method, params)
        if params == '' or key in self.generations:
            self.generations[key] = self.generations.get(key, 0) + 1
        self.entries.pop(key, None)

    def notification(self, packet):
        method = packet.get('method')
        for target in {
            'notifications/tools/list_changed': ('tools/list',),
            'notifications/prompts/list_changed': ('prompts/list',),
            'notifications/resources/list_changed': ('resources/list', 'resources/templates/list'),
        }.get(method, ()):
            self.evict(target)
        if method == 'notifications/resources/updated':
            uri = (packet.get('params') or {}).get('uri')
            if isinstance(uri, str):
                self.evict('resources/read', uri)

    def read(self, method, params=''):
        entry = self.entries.get((method, params))
        if entry is not None and entry['expiresAt'] > self.now():
            return json.loads(entry['value'])
        return None

    def write(self, method, params, value, generation, expires_at):
        if self.generations.get((method, params), 0) == generation:
            self.entries[(method, params)] = dict(value=stringify_json(value), expiresAt=expires_at)

    def reset(self):
        self.entries.clear()
        self.generations.clear()
