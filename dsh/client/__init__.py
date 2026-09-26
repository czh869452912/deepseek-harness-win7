"""
Browser client host halves (`@deepseek-ai/dsh-client-*`).

One module per browser package, each the port of that package's node half
(`reference/packages/client/<name>/src/index.ts`) or, for the extensions row,
`reference/packages/extensions/ui-cordis/src/index.ts`. `dsh/client/rows.py`
maps every shipped client row name to its class.

Compatible with Python 3.8.10 and Windows 7 SP1.
"""
