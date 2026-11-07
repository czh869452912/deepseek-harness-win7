"""Audited language adaptations of the pinned original Cordis guidance.

The source artifact retains original contracts. Only the Host language,
environment and JS-specific skill examples change here; browser code is reused.
"""
import copy
import json
from pathlib import Path

SOURCE_CONTRACTS = json.loads(Path(__file__).with_name('cordis_contracts.json').read_text(encoding='utf-8'))
PROMPT_ADAPTATIONS = [
    ("The restricted execution environment prevents accidental misuse; it is not a security boundary for malicious code. Services obtained by dynamic code connect to the real runtime.", "Python Host code executes in an owned Python worker with restricted builtins and computation imports. Obtain file, network, process and timer capabilities through Context services. This prevents accidental misuse; it is not a security boundary for malicious code. Services obtained by dynamic code connect to the real runtime."),
    ("- Read an optional Service with ctx.get('serviceName') by default and handle undefined.", "- Read an optional Service with ctx.get('serviceName') by default. Python Host code checks for None; browser Client code checks for undefined."),
    ("- Declare inject: ['serviceName'] on the returned Plugin object only when the Service is a hard dependency and the Plugin must enter waiting until Cordis reactivates it after the Service appears.", "- Declare plugin.inject = ['serviceName'] on the Python callable (or inject on the Client Plugin) only when the Service is a hard dependency and the Plugin must enter waiting until Cordis reactivates it after the Service appears."),
    ("```js\nreturn {\n  inject: ['requiredService'],\n  apply(ctx) {\n    ctx.requiredService.someMethod()\n    const optionalService = ctx.get('optionalService')\n    if (optionalService !== undefined) optionalService.someMethod()\n  },\n}\n```", "```python\ndef plugin(ctx):\n    ctx.get('requiredService').someMethod()\n    optional_service = ctx.get('optionalService')\n    if optional_service is not None:\n        optional_service.someMethod()\n\nplugin.inject = ['requiredService']\n```"),
    ("### Code: use plain JavaScript only\n\n- Host and Client code is not transformed by TypeScript, JSX, or a bundler.\n- Do not use TypeScript types, as, decorators, import, require, or JSX.\n- Client React code must use React.createElement(...); never write <Component />.\n- Do not assume that process, Buffer, window, document, fetch, native timers, or any other global is available. Query the corresponding platform's Builtins and Services first.", "### Code: Python Host and plain JavaScript Client\n\n- Host code is Python 3.8.10 source that declares a callable named plugin. Cordis mounts that callable; do not supply a JavaScript function body as Host code. Only inspected computation imports are available in the owned Host worker; obtain files, network, processes and timers through Context services.\n- Client code remains a plain JavaScript function body that returns a Cordis Plugin. It is not transformed by TypeScript, JSX, or a bundler; do not use TypeScript types, as, decorators, import, require, or JSX in Client code.\n- Client React code must use React.createElement(...); never write <Component />.\n- Do not assume browser globals or timers are available in the Client closure. Query the corresponding platform's Builtins and Services first. Python Host code must use Python 3.8 and Win7 compatible APIs."),
    ("- Host runs in the DSH Node.js process and is appropriate for files, networking, commands, Agent/Session access, Host Events, Services, model Tools, and JSON methods callable by the Client.", "- Host runs in an owned Python 3.8.10 worker connected to real DSH Context services and is appropriate for files, networking, commands, Agent/Session access, Host Events, Services, model Tools, and JSON methods callable by the Client."),
]
DEFINE_ADAPTATIONS = [
    ("Provide at least one of code.host and code.client. Each value is a plain JavaScript function body that returns a Cordis Plugin; no TypeScript, JSX, or import transformation occurs.", "Provide at least one of code.host and code.client. Host code is Python 3.8.10 source declaring a callable named plugin. Client code is a plain JavaScript function body returning a Cordis Plugin; no TypeScript, JSX, or import transformation occurs."),
    ("Define only validates parameters and syntax and records source:", "Define validates parameters, Python Host syntax, and JavaScript Client syntax, then records source without executing either half. Running can still fail due to execution errors, missing dependencies, or browser engine differences:"),
]


def replace_exact(text, adaptations):
    for original, replacement in adaptations:
        if text.count(original) != 1:
            raise ValueError('pinned Cordis language adaptation no longer matches its source')
        text = text.replace(original, replacement)
    return text


def native_contracts():
    result = copy.deepcopy(SOURCE_CONTRACTS)
    result['prompt'] = replace_exact(result['prompt'], PROMPT_ADAPTATIONS)
    define = next(tool for tool in result['definitions'] if tool['name'] == 'cordis_define')
    define['description'] = replace_exact(define['description'], DEFINE_ADAPTATIONS)
    define['parameters']['properties']['code']['properties']['host']['description'] = 'Python 3.8.10 Host source declaring a callable named plugin.'
    return result
