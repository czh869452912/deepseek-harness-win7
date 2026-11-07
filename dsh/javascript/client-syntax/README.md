# Client definition syntax

`dsh.javascript.client_syntax` compiles Client bodies before Package registration.
It runs this driver and the unmodified Acorn 8.15.0 module extracted from the local
Node v22.20.0 distribution on the existing private Win7 QuickJS worker. The
distribution's Acorn MIT notice is retained in `ACORN-LICENSE`; `manifest.json`
records source identity and resource hashes. No Node or npm install is required
by the product. Portable copying includes this directory under `dsh/`.

Acorn parses the source inside an ordinary function body using its latest grammar,
with ERM declarations, inline regular-expression modifiers, and duplicate named
capture groups across alternatives disabled, then QuickJS constructs the
original `new Function` async-arrow wrapper.
Neither parser calls the resulting function. Only the worker's fixed dummy body
and the trusted parser/driver execute. This permits lexical `new.target` and
rejects resource-management declarations unsupported by the fixed Node 22.20 gate,
without blocking the identifier `using` in ordinary expressions or literals.
The regex restrictions use Acorn's parsed modifier and normalized capture-name
state. Escapes, character classes, text literals, and `RegExp(...)` constructor
arguments are not scanned as regex syntax. Dynamic-import options, Unicode sets
(`v`), indices (`d`), and distinct named groups retain their existing acceptance.

The workflow compiler retains its existing global-script semantics. This private
Client check does not replace browser activation or certify every V8 grammar edge.
The dynamic Python Host has a separate process-owned evaluation boundary; this
Client parser neither implements nor qualifies that boundary.
