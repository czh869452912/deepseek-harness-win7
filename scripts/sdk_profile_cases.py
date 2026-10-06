SCENARIOS = ('normal', 'cancel', 'error')
VALUE_DAMAGES = ('missing-scenario', 'frame-missing', 'reply-order', 'reply-value', 'notification-method',
    'session-id', 'sequence', 'lifecycle', 'request-body', 'tool-schema', 'next-model', 'durable-missing',
    'durable-event', 'partial-model', 'partial-marker', 'partial-content', 'partial-causality', 'cancel-reason',
    'error-code', 'error-message', 'clock-window', 'clock-type', 'header', 'diagnostics', 'exit-type',
    'fixture', 'side', 'rows', 'module', 'closure-missing', 'closure-extra', 'group-missing', 'bytes',
    'root', 'python', 'executable', 'workspace', 'capture-root', 'capture-python', 'capture-executable', 'optional-bytes')
SOURCE_DAMAGES = ('pin', 'node', 'inputs', 'bytes', 'row', 'missing-scenario', 'fixture', 'input-shape')
EXTRACTED_DAMAGES = ('missing', 'source-missing', 'source-hash', 'source-row', 'source-stamp', 'source-input-shape') + tuple(
    damage for damage in VALUE_DAMAGES if damage != 'bytes')
