# Browser Client patterns

Dynamic Client is a plain JavaScript function body that returns a Plugin. Use the live Client Builtin/Service/Slots/Theme providers to confirm the closure and registration API. There is no TS/JSX/import or bundler step. React.createElement is supported where the React builtin exists. Do not assume window/document/fetch/process/Buffer or native timers.

## Select the narrowest contribution

- A normal model tool's textual output uses output.render. Do not mount a global panel to repeat an ordinary result.
- A custom dynamic Plugin run panel uses queried tool.view.cordis. The [echo.client.js](../examples/echo.client.js) example is for that Run card, not a persistent installed global overlay.
- A full settings page uses settings.section; settings.general.item is for one compact preference. Query the subtree for current keys, scope and props before registering.
- Sidebars, input areas and overlays use the exact selected Slot contract. Check occupants and replacement risk before replacing a region. A shell.overlay is global UI, not automatically Agent-scoped.
- Read conversation/session/workspace data from standard/owner props when provided. Do not fetch the same live data again through a guessed Host service or display inspection metadata as user data.

The sample uses slots.inject to wait for the selected slot, then slots.register and the owner key. Retain lifecycle ownership and use React effects with cleanup for component-owned work. Never return a React element from Plugin.apply; apply registers a component in a Slot.

## Themes

Query Theme.listTokens and the actual theme service. Override the smallest required token set and retain the returned disposer. For package-local presentation, prefer the provided owned styles helper or scoped component styling. Do not assume a global document stylesheet can be mutated and automatically undone. Client timers require timer injection and returned disposers, including when called inside React.useEffect.

## Python RPC

Pair [counter.host.py](../examples/counter.host.py) with [echo.client.js](../examples/echo.client.js): harness.handle('echo', handler) publishes a Package-private JSON method; host.call('echo', {text}) awaits it. The handler receives args, not a full Context. Convert data to supported JSON records, arrays and primitives. Catch errors and show useful state instead of leaving unhandled promise rejections.

Stop, update and unload revoke the old activation. Reloaded pages and new packages must use the active bridge. Browser disconnect, missing provider, approval waiting, Python exception, invalid RPC data and render failure are separate diagnoses; inspect the exact Package and Run diagnostics.

## Page overlay example

Use [echo.overlay.client.js](../examples/echo.overlay.client.js) with the Python counter for a page overlay during the dynamic Plugin lifetime. Query shell.overlay first. Its visibility outside a Run card does not make it survive Host restart or provide durable state. Exercise an actual browser render and Python call; Host-only RPC tests cannot establish Client activation.
