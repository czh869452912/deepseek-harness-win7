# Windows 7 Desktop carrier

This shell pins Electron **22.3.27**, Chromium108 and Node16.17.1. Its backend
is the repository's Python3.8.10 canonical Cordis composition. The original
rc.3 web application and its active ClientModules bundles are served over
`dsh-app://app`; no HTTP listener is mounted.

For a development checkout:

```powershell
<electron-22.3.27>/electron.exe apps/desktop --root . --python .venv/Scripts/python.exe
```

The application owns `$DSH_HOME/profiles/desktop` (default `~/.dsh`). Ctrl+,
opens Plugins in the main window. The Application menu exposes a separate local
folder/ZIP import for offline packages. The Windows tray keeps the main window
available after closing it; Quit releases the Host and profile lease. Both
renderers use context isolation, sandboxing and disabled Node integration.
On upgrade, an unchanged default session configuration preserves a purely
plaintext `$DSH_HOME/sessions` directory as `compression: none` in memory.
An empty directory still uses zstd. Explicit compression settings, custom roots
and mixed-encoding refusal retain the canonical backend policy. Startup does
not convert, remove or downgrade historical generations, or rewrite user patches.
Unsupported newer generations remain unreadable by this version.
Only the owned top-level `dsh-app://shell` frame may invoke management IPC.
The owned app frame has separate environment/guide IPC. The preload does not
request these services while the main window temporarily displays `about:blank`.

Desktop uses the existing Python plugin ABI and accepts local folders or ZIP
packages. The original manager renderer is retained verbatim; its served input
placeholder and locale descriptions identify the supported package format.
Package mutations are serialized. A stopped-profile shadow transaction records
the exact old/new manifest and managed plugin bytes before publication. Host
readiness commits the generation; failed readiness or an interrupted pending
transaction restores the old generation. An interrupted committed transaction
finishes cleanup. Unexpected profile/plugin changes preserve the transaction
for inspection. User settings, sessions and installation junctions are outside
these snapshots. Retained upgrade generations use the canonical history store.

The upstream v3 frame format is unchanged. Windows stdio carries its binary
request/response frames; bounded stderr lifecycle messages replace Node's
fd3/fd4/fd5 process ABI. The shell streams protocol responses, propagates
cancellation and bounds buffered request bodies. Forced shutdown owns the
Windows child process tree, including a development venv redirector.

`scripts/build_desktop_inputs.mjs` reproduces the codec, locale, transport and
manager renderer from the clean pinned rc.3 Source checkout. The generated
`source-input.json` records every source/output hash. Development verification
uses `scripts/run_desktop_smoke.py --output <fresh-directory>` (optionally
`--limited-shell`); its parent owns the process through shutdown and keeps logs
in a regular file. Do not detach a GUI test with inherited temporary pipes.
The shell tolerates only `EPIPE` on inherited stdout/stderr when its launching
terminal closes; other stream errors remain errors. Packaged applications reject all
development overrides. The smoke entry verifies real RPC/streaming, renderer
isolation and actual plugin rollback. Expected control-stream errors during
Host replacement remain separately recorded, followed by a fresh baseline
check. Installer qualification, public update-channel publication and
physical Win7 acceptance are separate milestones.

Standard installation may continue with a limited environment. Its finish page
and a dismissible first-launch notice point to the local `win7-setup.html` guide.
Build the separate x86/x64 prerequisite ZIP with
`scripts/build_windows_upgrade.py --external-prereq-dir <verified-inputs> --output-dir <fresh-directory>`.
This ZIP contains Microsoft prerequisites and the explicit administrator entry
`upgrade-win7.bat`; it does not add x86 application runtime support. AIO embeds
the matching prerequisite set. The x86 AIO includes both OS architectures so its
ia32 application also works on x64 Windows; the shared .NET installer appears
once. Neither builder executes the system installers.

Both application architectures use pinned Python3.8.10, Electron22 and native
SQLite/ICU/Zstandard/QuickJS/ripgrep/WinPTY resources. Resource selection follows
the Python process width, including WOW64. The x86 lock excludes the incompatible
CPython3.7 pywinpty extension: only its separately verified WinPTY C ABI binaries
and licenses are used through ctypes.

Prepare an x86 runtime with
`scripts/prepare_x86_runtime.py --inputs-dir <external-downloads> --stdlib-runtime <python-3.8.10-runtime> --output <fresh-win32-runtime> --download`.
The fixed archive/wheel identities are in `scripts/x86-inputs.json`. Then run
`scripts/build_portable.py --architecture x86 --python-runtime <win32-runtime> --site-packages <win32-runtime>/Lib/site-packages --output-dir <fresh-output>`.
The x86 builder requires explicit inputs and output so it cannot replace the
default x64 Portable. For Desktop use
`scripts/build_desktop.py --architecture x86 --portable-dir <current-x86-portable> --electron-archive <pinned-ia32-zip> --edition both --external-prereq-dir <verified-inputs> --output-dir <fresh-output>`.
Actual development smoke tests of its packaged host can use that host's Python
to run `scripts/run_desktop_smoke.py --root <desktop-unpacked>/resources/harness --electron <ia32-electron> --output <fresh-output>`.

Desktop updates retain the pinned Source coordinator, update states and shell IPC.
The Win7 adapter installs a complete Standard NSIS package, including its paired
Python host. `--update-config <json>` on the desktop builder embeds a configuration
with exactly `schemaVersion: 1`, `channel: "win7-electron22"`, an HTTPS
`manifestUrl` and a PEM Ed25519 `publicKey`. Without it, checks return idle. This
channel must belong to the Win7 distribution; upstream Electron44 feeds are
incompatible. No update channel or signing key is generated or published by a build.
For a private CA, the optional `caCertificate` field holds a PEM CA chain (up to
8192 bytes); it applies to feed, redirect and installer requests while retaining
hostname verification. See [the LAN deployment guide](../../docs/desktop-lan-updates.md).

The release envelope contains base64 `payload` and Ed25519 `signature` over the
exact payload bytes. The signed payload binds version, architecture, Electron,
Python, publication/expiry (at most 90 days), installer HTTPS URL, byte count and
SHA-256. Checks reject expired, incompatible and unverified metadata. Downloads
are bounded and verified before stopping the Host. A hidden PowerShell helper
waits for the desktop process to exit, rechecks the installer hash, then opens
the interactive administrator installer. Successful installer completion removes
the downloaded EXE; handoff failures retain `install.log` in the owned update
temporary directory. User sessions remain in DSH_HOME.

Release operators can create the envelope with
`node scripts/sign_desktop_update.cjs --installer <built-standard-exe> --version <version> --artifact-url <https-url> --manifest-url <https-feed-url> --private-key <external-ed25519-pem> --output <fresh-json>`.
The private key is never embedded. Publishing the signed feed/installer and
real administrator installation are separate release operations.
For an x86 feed, add `--architecture x86` to the signing command and select the
x86 Standard installer. Each running updater rejects the other architecture.
