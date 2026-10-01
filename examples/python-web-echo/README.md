# Installed Python Host and original Web Client example

This opt-in example adds a small overlay to the original Web application. Its
button invokes an installed Python service through Connection and Typert Remote,
then shows the returned text, call count and version. It uses the original
shell's shared React and slot services; it does not replace or edit browser code.

Install the directory or its complete ZIP while the Web profile is stopped:

```powershell
dsh plugin --profile web add .\examples\python-web-echo
dsh --profile web --no-open
```

To publish a reviewed ZIP, use the native CLI:

```powershell
dsh plugin --profile web pack .\examples\python-web-echo python-web-echo-1.0.0.zip
dsh plugin --profile web add python-web-echo-1.0.0.zip
```

`dsh.release.files` is the explicit author-maintained release set. Packing and
directory installation copy only those files; ZIP installation rejects extra
files. All declared Web receipt artifacts, Python source, package descriptor,
README and LICENSE must be included. This author-written example has no dynamic
runner origin; exported projects retain their existing `dsh.sourceExport` record.

Remove with `dsh plugin --profile web remove @example/python-web-echo` after
stopping the profile. A restart loads both faces from the installed files;
the transient counter starts at zero. Runtime unload removes the service,
Typert descriptor and Host Client graph row. The pinned original HMR keeps the
page's initial boot graph: the existing overlay remains until page reload, and
its Remote calls are rejected after Host withdrawal. Reload then removes the
Client Remote mount and overlay. Stopping and removing the installed package
prevents both faces from loading on the next boot.

The package ships ready-to-serve `client/client.js` and its source map, an explicit
SHA-256 build receipt bound to the pinned Host protocol, and a Python Typert
artifact. Both faces use `remote/contract.json`. No Node/pnpm, TS compiler, system
Python or Internet download is needed by a complete Portable installation.

Developers rebuild the supplied plain JavaScript example with
`.venv\Scripts\python.exe scripts/build_python_web_example.py`. The script wraps
the authored body in the original `__ModuleLoader__` format; it is not a general
TS/TSX compiler. Run the Python package tests and the actual Chromium journey
before sharing edits. Hashes verify bytes, not the trustworthiness of code.

The example is trusted Python code using experimental Plugin API 1. The codec's
JSON Schema subset is the same subset supported by the Host tools API. The
Client's small codec covers only this example's string/integer/object contract.
Current Windows/modern Chromium results do not certify Win7's target browser.
Arbitrary dynamic Client source conversion, additional offline dependencies,
assets with relative imports and complex Remote schemas still need separate
build and integration validation. The package is not mounted in shipped defaults.
