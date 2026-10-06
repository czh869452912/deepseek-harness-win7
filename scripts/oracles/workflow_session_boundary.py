import copy


class WorkflowSessionBoundary:
    def __init__(self, scenario):
        self.frames = []
        self.snapshot = None
        self.required_disposals = scenario.get('waitDisposals', 0)
        if type(self.required_disposals) is not int or self.required_disposals < 0:
            raise ValueError('Workflow observation requires a nonnegative disposal count')
        self.semantic_type = ('log' if scenario['name'] == 'dropped-child-continuation' else 'agent-end')
        self.semantic_seen = self.required_disposals == 0
        self.terminal_seen = False
        self.disposed = set()

    def record(self, message):
        self.frames.append(copy.deepcopy(message))
        if message['type'] == 'result':
            self.terminal_seen = True
        if message['type'] == self.semantic_type:
            self.semantic_seen = True
        if message['type'] == 'child-dispose':
            self.disposed.add(message['callId'])
        if (self.snapshot is None and self.terminal_seen and self.semantic_seen
                and len(self.disposed) >= self.required_disposals):
            self.snapshot = copy.deepcopy(self.frames)
        return self.snapshot is not None
