# Native Python source export

Native implementation: [cordis_export.py](../../../dsh/extensions/cordis_export.py). This manifest supplies the active Loader identity required by DeepSeek request inventory; the Python registry resolves implementation. See the [Win7 delivery guide](../../../docs/plugin-distribution-win7.md) for explicit mounting and installation. This is an optional native extension, not part of the original default Creative workflow.

## Model Experience

### Export tool while mounted in the requesting scope

#### What the model sees

An owned cordis_export schema exports an exact owned Package with explicit placement, license and source provenance. It is separate from the default seven Cordis tools. This native extension has no upstream TS-generated catalog entry; its exact parameter/output schema is owned by the linked Python source.

##### Verbatim tool description

```markdown
Export an exact owned dynamic plugin version to a native Python source project. Host projects install with the existing Python directory/ZIP installer. Session projects include a user-preset fragment. Projects containing Client source must first use dsh plugin --profile <profile> build <project>, then pack/install and verify in the browser. Build supports exported plain JavaScript, not arbitrary TS/JSX projects. Supply explicit license text. Review and test before sharing.
```

#### Token effect

Mounting adds one tool schema to visible requests. The rendered result appends release identity, source directory, file names and Client-build requirement to tool history; its size varies with the exported project. The exporter starts no separate model request. Disposal removes future tool availability.

#### KV Cache effect

Mounting, disposal or changes to the schema alter earlier serialized tool bytes. Stable registration preserves those bytes; each export adds a new tool result after prior history. Cache availability and eviction are provider concerns, and this plugin adds no cache controls.

## Known Limitations and Deferred Work

Build supports exported plain JS, not arbitrary TS/JSX compilation. Export does not install, approve or prove browser activation. This is a native-only registry entry without TS build configuration. No ./invariant companion: it has no independent paired value relation. Ownership, filesystem effects and installation are covered by tests/test_python_plugin_export.py; canonical request visibility is covered by tests/test_win7_authoring.py.
