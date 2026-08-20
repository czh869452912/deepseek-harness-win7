---
name: editing-cordis-compositions
description: Use when creating, changing, or validating a Cordis composition for this harness — writing or editing an agent preset, adding or removing a plugin row, deciding whether something belongs to the host composition or to one session, checking whether a preset you authored actually mounts, or diagnosing a row that mounted but contributed nothing.
---

# Editing Cordis compositions

Every capability in this harness is a plugin row in a `cordis.yml` or preset yaml. There is no separate configuration language: changing what an agent can do means changing which rows are composed for it.

## Off-limits

**Never edit, delete, or overwrite a preset that ships with the deployment** — the `agent-presets` directory beside the deployment's own config, which supplies `standard`, `code`, `minimal`, and `cordis`. Never escalate the sandbox to reach it, even when a change there looks quicker. An upgrade overwrites that install, and corrupting `cordis` disables preset authoring itself. Reading a shipped composition is the intended way to start; writing to one is not, and neither is editing the host composition to work around a preset limitation.

To change what a shipped preset does, copy it and edit the copy. Locally authored presets under the user root are yours to create, edit, and delete.

## Decide the plane first

Two planes, and the choice is not about how "agent-related" something feels — it is about whether the thing must be shared.

**Host composition.** The registries themselves (`tools`, `systemPrompt`, `agents`, `agent-loop`, `sessions`), anything crossing sessions (persistence, session query, storage, settings, credentials, telemetry), the sandbox and approval stack, the model route, and the subagent registry with its spawn/fork backends. One instance for the process.

**Agent preset.** What one session contributes to those registries: its tool plugins, its persona and prompt sections, its compaction policy. One instance per session, mounted under that session's scope and unwound with it.

**A service with a consumer outside the agent plane cannot move into a preset.** `subagents` is the worked example: the registry answers cross-session queries for the host api-proxy, so a per-session copy both starves that host row — it waits forever for a service nothing provides — and collides on the second session, since a provider name registers once. The preset contributes the delegation *tools*; the registry and its backends stay host-side.

A preset is a directory holding one `agent.cordis.yml`, optionally beside a `preset.yml` carrying display metadata — `name` and `description` (and, for shipped presets, a roster `order`). Write the metadata too: a preset without it shows up in every picker as its bare directory name.

Locally authored presets live one directory per preset under `${DSH_HOME:-$HOME/.dsh}/.agent-presets/`, and the shipped set sits beside the deployment's own config. Use those when the user asks where to look. A deployment can configure other roots, so the path you read or edit comes from `list()` or `resolve()` — which is also where `copy()` reports what it just created.
