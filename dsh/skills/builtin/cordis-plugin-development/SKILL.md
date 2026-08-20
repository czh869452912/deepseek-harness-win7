---
name: cordis-plugin-development
description: Create, modify, debug, or extend dynamic Cordis Plugins, including Host Services and Events, dynamic Tools, version updates, and runtime diagnostics.
---

# Develop Dynamic Cordis Plugins

First determine whether a capability belongs on Host or Agent Presets, then query the real interface before writing code. Never infer a complete API from a Service name or Event payload.

## Core Plugin Concepts in Python

1. **Service Registration**:
   ```python
   ctx.set_service("my_service", MyService(ctx))
   ```

2. **Reversible Effects**:
   ```python
   def cleanup():
       ...
   ctx.effect(cleanup)
   ```

3. **Event Dispatching Modes**:
   - `emit`: synchronous notifications
   - `waterfall`: middleware processing `(data, *args, next_fn)`
   - `serial`: sequential async execution
   - `parallel`: concurrent async execution
   - `bail`: short-circuiting first non-None result

4. **Dynamic Tools**:
   ```python
   tools = ctx.get("tools")
   tools.register_tool({
       "name": "my_tool",
       "description": "...",
       "parameters": {...},
       "execute": my_exec_fn
   })
   ```
