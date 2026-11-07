# Observe lifecycle without rebuilding the runtime

Use the actual dynamic tools first: define, run, exercise the feature, stop and verify withdrawal. Inspect contracts progressively. The shipped examples already establish the facade bindings; read framework implementation to resolve a specific observed problem, rather than building a replacement runtime before the first call.

For combined state/event/timer behavior, [stateful.host.py](../examples/stateful.host.py) provides win7_state_counter, win7AuthoringStateful and the custom win7-authoring/ping event. State is created per activation. A separate trusted verifier can retain a state reference across stop, emit that custom event and observe whether it changes. Dynamic code.host cannot dispatch arbitrary framework events, and JSON RPC snapshots are not live references.

[verify_stateful.py](../examples/verify_stateful.py) supplies that external check using canonical run_profile. It creates its own temporary home and Agent, uses the real dynamic runner and tools, checks values 1/2, event/timer activity, stop withdrawal and stable old state, then reactivates and checks 1. It closes the private profile, makes no model request and does not load the user home. It uses native development services, not the experimental API contract for ordinary packaged plugins; do not paste it into code.host or import full Context to bypass the facade.

From a repository, using absolute paths derived from the skill base:

```powershell
& '<installation>\.venv\Scripts\python.exe' '<skill-base>\examples\verify_stateful.py' '<installation>' '<your-workspace>\stateful.host.py'
```

Portable uses `<installation>\python.exe` instead. If only the tool name was changed, supply it as the final positional argument, for example eval_counter. The checker expects the sample's state service, event and state fields; adapt those checks explicitly if changing that contract. A failing check is a diagnostic, not a reason to skip cleanup or weaken validation.

Retain stdout/stderr and the generated source. Success ends with a JSON record containing passed: true and values: [1, 2, 1]. This verifies Python behavior on the current machine; it does not validate a Client, certify Win7 or replace install/cold-start checks.

For Client work, exercise an actual browser and Python call during the dynamic activation. Host-only RPC tests cannot establish browser activation.
