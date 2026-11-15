"""Incremental, capability-independent reconstruction of tool declarations."""
from dsh.cordis.json_text import stringify_json
from .json import deep_freeze


class ToolHistoryProjection:
    def __init__(self):
        self.headers = {}
        self.declared = {}
        self.active = []
        self.available = set()
        self.baseline_seq = None
        self.history = deep_freeze(dict(tools=[], updates=[]))

    def apply(self, event):
        data = event['data']
        if event['type'] == 'request/header':
            tools = data['header'].get('tools', [])
            self.headers[event['seq']] = tools
            redeclared = any(tool['name'] in self.declared and
                stringify_json(self.declared[tool['name']]) != stringify_json(tool) for tool in tools)
            if self.baseline_seq is None or data['reason'] == 'series' or data.get('startsSeries') or redeclared:
                self.baseline_seq = event['seq']
                self.declared = {tool['name']: tool for tool in tools}
                self.history = deep_freeze(dict(tools=tools, updates=[]))
                self.available = set(self.declared)
            self.active = tools
        elif event['type'] == 'developer/message':
            message = data['message']
            definitions = self.headers.get(data.get('headerSeq'), [])
            additions = []
            for block in message['content']:
                if block['type'] != 'tool-addition':
                    continue
                tool = next((tool for tool in definitions if tool['name'] == block['toolName']), None)
                if tool is None:
                    raise ValueError('tool history: missing definition for ' + block['toolName'])
                additions.append(tool)
            self.declared.update((tool['name'], tool) for tool in additions)
            for block in message['content']:
                if block['type'] == 'tool-addition':
                    self.available.add(block['toolName'])
                elif block['type'] == 'tool-removal':
                    self.available.discard(block['toolName'])
            self.history = deep_freeze(dict(tools=self.history['tools'],
                updates=list(self.history['updates']) + [dict(messageId=message['id'], additions=additions)]))

    def snapshot(self):
        if len(self.active) != len(self.available) or any(tool['name'] not in self.available for tool in self.active):
            return deep_freeze(dict(tools=self.active, updates=[]))
        return self.history
