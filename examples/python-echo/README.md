# Python Echo Plugin

Experimental API version 1. A standard-library Python tool plugin for the Win7
host. The `python_echo` tool returns `Python echo: <text>`. Its Cordis `tools`
injection and caller-owned registration use the existing framework lifecycle.

Stop the selected profile before installation, replacement or removal. From the repository:

```powershell
.venv\Scripts\python.exe dsh.py plugin --profile web add .\examples\python-echo
.venv\Scripts\python.exe dsh.py --profile web
```

After stopping the host:

```powershell
.venv\Scripts\python.exe dsh.py plugin --profile web remove @example/python-echo
```

Portable users invoke the same arguments through `dsh.bat`. This plugin requires
no Node, pnpm or external Python libraries. Installation copies the package;
later edits in the development directory do not modify the installed snapshot.

Developers can produce a ZIP with `package.json`, `cordis.patch.yml`, `python/`,
this README and LICENSE at its root, or below one enclosing directory. Install
it with `dsh plugin --profile web add ./python-echo.zip`. Node/pnpm are unnecessary
for both producing this Python-only archive and installing it.

Package-local imports use relative imports, as shown by `.formatting`. Import
host APIs from `dsh.plugin_api`; package loading does not add the plugin source
directory to global `sys.path`. This is module naming, not a dependency sandbox.
Plugin code has the permissions of its host process. Installation validates
metadata, paths and Python syntax without executing package code; activation
executes it and may fail.

After publishing a different version of the same package, stop the host and use
`dsh plugin --profile web upgrade ./python-echo-v2.zip` (a directory also works).
Run `dsh plugin --profile web versions @example/python-echo` to see the current
and retained source versions. Restore the most recently replaced version with
`dsh plugin --profile web rollback @example/python-echo`, or append a retained
version label. Restart the profile to load the selected source. Versions are
immutable labels, not ordered PEP 440 constraints. Installation still does not
execute the plugin; if activation fails, stop the host and explicitly roll back.

Changed installed or archived source files block replacement. Package removal
keeps historical source snapshots under the profile; it does not remove plugin
business data stored elsewhere. Source rollback does not reverse data migrations.

Dependencies, automatic activation rollback, live source reload and
custom browser clients remain separate implementation/acceptance work. API 1
currently requires an empty dependency list and minimum-version arrays;
it does not implement PEP 440 constraints. Changed installed files block removal
so user modifications are not silently deleted. Store user data outside the
installed package directory.

See `docs/research/2026-09-30-python-plugin-local-delivery.md` for the descriptor,
and `docs/research/2026-10-01-python-plugin-versions-progress.md` for version
transactions and observed validation scope. Win7 real-machine testing
is still pending; current Windows tests do not certify it.
