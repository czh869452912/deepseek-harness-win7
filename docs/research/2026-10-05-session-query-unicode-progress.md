# Unicode request identities — 2026-10-05

The previous code-point sort disagreed with the pinned source's ICU localeCompare in 96 of 160 baseline fingerprints. Equal-collation strings also incorrectly allowed four reversed-filter cursors. The canonical engine now uses stable ICU sorting for values and serialized clauses. The expanded actual source/native observer measures 1849 comparisons, 180 fingerprints and five real cursor refusals, including non-FCD normalization, ignorable characters, embedded NUL and unpaired UTF-16 surrogates.

Private ICU 78.2 uses Unicode 17 and CLDR 48. Unchanged release-78.2 source is compiled with pinned LLVM-MinGW MSVCRT, static C++ runtime, Windows 7 target and zero linker timestamps. Matching official common data, seven licenses, archive hashes, build commands and exact DLL identities are retained. Node and the compiler are development inputs only. File validation precedes loading and Portable replacement; common data is bound in memory and external data files are disabled.

The complete gate adds 25 mandatory lanes (249 total) and one paired driver (48 total). Extracted Python must match the fresh source's full observation SHA-256 and default locale, as well as exact candidate module/DLL paths, versions and normalization. Focused regression results do not constitute clean-candidate acceptance. Earlier fixture/manifest observer failures are preserved in raw logs.

Full clean-candidate verification and task acceptance are pending. Full regex/folding/extraction, other domain locale orders, all provider histories, physical schema-19, original startup cancellation and global migration remain open. No predicate, timing or exception is relaxed. Real Win7 is deferred and accepted_upstream remains null.
