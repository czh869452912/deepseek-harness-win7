# Minimal historical inputs

The gzip members in this directory preserve original uncompressed bytes. The
manifest records their original archive, member path, length and SHA-256; nested
members also record the containing ZIP and its SHA-256. Original archives remain
outside this checkout under the evidence storage policy. These fixtures neither
replace those archives nor establish acceptance for a newer candidate.

`tests/release_gate_fixtures.py` uses selected rc.3 observations to exercise the
retained receipt-parser schema. Its compound success case uses a synthetic ZIP
and synthetic candidate identity. Most Native inputs are freshly executed against
the checkout's retained domain helpers. FS, JSONL and rc.1 parser models use the
original literal Native input with explicit placeholder hashes for newly required
schema fields. Source descriptor copies may bind the current observer/corpus hash
so parser controls can exercise their metadata relationship; the original fixture
bytes remain unchanged. Derivations are recorded in the run's `parser-fixtures`
and `parser-models` directories.

Those derived values are **unit-test models, never Source or release evidence**.
They cannot pass a current pinned Source file-identity check. Current SDK and file
metadata inputs in the compound case are separately captured from current Source.
Actual current Source, paired contracts and extracted product qualification must
execute their own frozen lanes; these parser tests cannot substitute for them.
