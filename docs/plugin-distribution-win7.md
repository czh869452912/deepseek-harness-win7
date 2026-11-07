# Native delivery on Win7

This optional native extension is separate from the original dynamic Cordis workflow. Use it only when the user requests persistent source delivery. It is not mounted by default or required by the cordis-plugin-development skill.

To expose cordis_export, explicitly mount the existing row `name: '@deepseek-ai/dsh-tool-python-export'`: insert it with a CLI profile patch, or append it to a user-owned Web preset copy. Do not edit a shipped preset or mount another development-skill provider.

## Locate commands before building

Use the known installation root containing dsh.py and dsh.bat, independently of the task working directory. In a repository check the exact .venv/Scripts/python.exe path and invoke both interpreter and dsh.py by absolute path. Portable also contains python.exe at its root for standalone verification scripts. Do not derive the installation root from a user-copied skill directory.

Do not recursively search .goose/out, node_modules or dist for an interpreter. A temporary Host plugin runs through cordis_define/run; it does not require launching another Python interpreter or a TS build. The [verification reference](../packages/preset/agent-presets/presets/cordis/skills/cordis-plugin-development/references/verification.md) gives an optional external stateful checker command.

## Native Host project

An ordinary source project contains package.json, cordis.patch.yml, README.md, LICENSE and python/<module>/ files. Import Plugin from dsh.plugin_api, implement apply(self, ctx, config), declare inject and register through ctx.get('tools').register. Use the full raw JSON Schema root for native tool parameters. Do not reference injected dynamic harness globals in an ordinary module.

The repository examples/python-echo is a complete standard-library project with dsh.python apiVersion 1, sourceRoot, entry, minimum numeric version arrays, dependencies: [] and dsh.release.files. Its entry is echo.plugin:EchoPlugin; package-local imports are relative. Public API 1 remains experimental. A minimal package descriptor looks like:

```json
{
  "name": "@author/my-plugin", "version": "1.0.0", "license": "MIT",
  "dsh": {
    "bundle": {"patch": "cordis.patch.yml"},
    "python": {"apiVersion": 1, "sourceRoot": "python", "entry": "my_plugin.plugin:MyPlugin",
               "minPythonVersion": [3, 8, 10], "minHostVersion": [0, 1, 5], "dependencies": []},
    "release": {"formatVersion": 1, "files": ["package.json", "cordis.patch.yml", "README.md", "LICENSE",
                          "python/my_plugin/__init__.py", "python/my_plugin/plugin.py"]}
  }
}
```

Create an empty python/my_plugin/__init__.py and this python/my_plugin/plugin.py:

```python
from dsh.plugin_api import Plugin


class MyPlugin(Plugin):
    name = 'my-plugin'
    inject = ['tools']

    def apply(self, ctx, config):
        ctx.get('tools').register({
            'name': 'my_echo', 'description': 'Echo a string.',
            'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}},
                           'required': ['text'], 'additionalProperties': False},
            'execute': lambda args, execution: args['text'],
            'output': {'schema': {'type': 'string'},
                       'render': lambda args, value: [{'type': 'text', 'text': value}]},
        })
```

cordis.patch.yml contains:

```yaml
- insert:
    - id: my-plugin
      name: '@author/my-plugin'
```

Supply README.md with usage and actual LICENSE terms matching package.json. These files and the descriptor above form a standalone Host project, including in Portable where the repository example is absent. Registration is owned by the plugin Context and is withdrawn on unload. Metadata/path/Python checks happen during installation without executing plugin code; real activation still needs testing.

## Dynamic source export

Explicitly mounting tool-python-export enables cordis_export. The default seven Cordis tools deliberately do not include it. Inspect the owned exact pluginId/packageId before export. Supply a new relative workspace directory, author-owned package name, release version, placement, isolateServices and explicit license/licenseText. Do not overwrite the running installation or shipped presets.

- host placement installs shared Host source through the profile's Loader.
- session placement includes preset.fragment.yml. After installing the package, append that fragment to a USER preset, then select that preset. Declare every additional Host service in isolateServices; do not assume standing presets are one instance per session.
- A dynamic ID and Package ID are provenance, not the public package name or release version.
- An exported Host body uses the provided Python packaged-source adapter; a hand-written native class is a separate entry shape.

For exported projects dsh.sourceExport.files and dsh-export.json retain provenance. Hand-written projects instead use dsh.release.files. Pack validates an explicit reviewed file set; include all required Python files, patch, metadata, README, LICENSE, artifacts and dependency files. Do not pack .env, credentials, caches or a virtualenv.

## Build, pack, install and cold start

Use the actual profile you will run. In Portable these commands go through dsh.bat; in a repository use .venv\Scripts\python.exe dsh.py with the same arguments.

```powershell
dsh.bat plugin --profile web build C:\work\my-export
dsh.bat plugin --profile web pack C:\work\my-export C:\work\my-plugin-1.0.0.zip
dsh.bat plugin --profile web add C:\work\my-plugin-1.0.0.zip
dsh.bat --profile web
```

Build is only needed for exported Client source. It packages supported plain JS with the original evaluator and Remote bridge; it is not a TS/JSX compiler and does not ensure a selected Slot exists in the installed UI. Choose the appropriate persistent Slot when delivering a dynamic Run-card experiment, then check the browser. Rebuild after Client source changes. Host-only handwritten examples go directly to pack/add.

Stop the target profile before add/upgrade/rollback/remove; closing the browser alone is insufficient. Installation copies source into a managed snapshot; later development edits do not change the installed package. Add accepts a directory, ZIP, or HTTPS ZIP with an explicit --sha256 digest. Use install validation followed by actual tool/RPC/browser execution after cold start, including Chinese and space-containing paths.

## Upgrade, rollback and removal

```powershell
dsh.bat plugin --profile web upgrade C:\work\my-plugin-1.1.0.zip
dsh.bat plugin --profile web versions @author/my-plugin
dsh.bat plugin --profile web rollback @author/my-plugin 1.0.0
dsh.bat plugin --profile web remove @author/my-plugin
```

Restart after selecting a version. Release labels are immutable identities, not version-range resolution. Activation failure does not imply automatic rollback: stop the profile and explicitly restore a retained version. Changed managed files block destructive replacement. Keep business data outside installed source; source rollback cannot undo a data migration. For session placement retain/repair user-preset references when removing a package; do not leave a reference and claim the preset will still start normally.

## Win7 checklist

- Python 3.8.10 syntax/standard library only: typing.List/Dict rather than builtin generics, no match or removeprefix/removesuffix, no newer OS APIs without a supported fallback.
- Use explicit UTF-8 file I/O, pathlib/os.path and Windows-safe paths; test Chinese, spaces and newline behavior. Use mounted filesystem policy for task workspace operations.
- Query shell capability. Prefer the actual powershell.exe service on Windows, with supported cmd fallback; do not require modern pwsh.exe or POSIX/bash commands on Win7. Standard/PS2 limitations must be handled separately from developer PS5.1 convenience commands.
- Start with the standard library. Additional libraries need supported expanded pure-Python exact name==version dependency closures and file/hash records. No arbitrary pip resolution, native wheel/DLL/PYD loading or Node install step on the target machine. Inspect the current dependency implementation before authoring a lock record.
- Use explicit release file lists and supported experimental API descriptors. A successful compile/build does not certify arbitrary dependencies or Client functionality.
- Validate stop, dependency disappearance/recovery, cancellation, unload/reinstall, old references, cold start and selected upgrade/rollback behavior. Record modern Windows checks separately from Win7 target-machine observations.
