"""
Command line argument parser for dsh matching reference/apps/cli/src/args.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import sys
from typing import Any, Dict, List, Optional, Tuple


HELP_TEXT = """Usage: dsh [options] [command] [args...]

dsh: boot a DeepSeek Harness profile — an ordered stack of plugin-bundle patch layers under your own overrides.

Options:
  -V, --version              output the version number
  --profile <name>           the profile under $DSH_HOME/profiles to boot
  --patch <path>             extra patch-list overlay applied after the profile layer (repeatable)
  --dump-config              print the composed profile tree and exit
  --dump-default-config      print the profile tree without its user layer or --patch overlays and exit
  -h, --help                 display help for command

Commands:
  web [options] [args...]    boot the web profile (alias of --profile web); the web app's own flags follow
  plugin [options] [args...] manage a profile's plugins by forwarding the remaining arguments to pnpm in the profile directory

Examples:
  dsh --profile web                          boot the web profile (same as: dsh web)
  dsh --profile headless "run the tests"     answer one task, print the result, and exit
  dsh --profile tui --patch ./extra.yml      boot a custom profile with one extra overlay
  dsh --profile tui --resume <session>       arguments after the launcher flags reach the app
  dsh --profile web --help                   the web app's own flags and help
  dsh plugin --profile tui add <package>     install a plugin into the tui profile
"""


def _error(msg: str, code: int = 1) -> None:
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(code)


def _help(code: int = 0) -> None:
    sys.stdout.write(HELP_TEXT)
    sys.exit(code)


def _version(version: str) -> None:
    sys.stdout.write(f"{version}\n")
    sys.exit(0)


def parse_dsh_args(argv: List[str], version: str = "1.2.3") -> Dict[str, Any]:
    """
    Parse launcher argv matching parseDshArgs in TS.
    Returns:
      ProfileInvocation: {'mode': 'profile', 'profile': str, 'patches': List[str], 'args': List[str]}
      DumpConfigInvocation: {'mode': 'dump-config', 'profile': str, 'defaultOnly': bool, 'patches': List[str]}
      PluginInvocation: {'mode': 'plugin', 'profile': str, 'args': List[str]}
    """
    if not argv:
        _error("--profile <name> is required")

    # Check top-level help / version when no profile or command
    if argv[0] in ("-h", "--help"):
        _help(0)
    if argv[0] in ("-V", "--version"):
        _version(version)

    # Check if first token is a subcommand
    first = argv[0]
    if first == "web":
        return _parse_web_command(argv[1:], version)
    if first == "plugin":
        return _parse_plugin_command(argv[1:], version)

    # Top-level command:
    # Owns: --profile <name>, --patch <path>, --dump-config, --dump-default-config
    # Ends at first token it does NOT own.
    profile: Optional[str] = None
    patches: List[str] = []
    dump_config = False
    dump_default_config = False
    args: List[str] = []

    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]

        if tok == "--profile":
            if i + 1 >= n:
                _error("--profile needs a name")
            profile = argv[i + 1]
            i += 2
            continue
        elif tok.startswith("--profile="):
            profile = tok[len("--profile="):]
            i += 1
            continue

        if tok == "--patch":
            if i + 1 >= n:
                _error("--patch needs a path")
            patches.append(argv[i + 1])
            i += 2
            continue
        elif tok.startswith("--patch="):
            patches.append(tok[len("--patch="):])
            i += 1
            continue

        if tok == "--dump-config":
            dump_config = True
            i += 1
            continue

        if tok == "--dump-default-config":
            dump_default_config = True
            i += 1
            continue

        if tok in ("-V", "--version"):
            _version(version)

        # Reached first token launcher does not own
        break

    # If stopped at subcommand 'web' or 'plugin', check rejectParentOptions
    if i < n and argv[i] in ("web", "plugin"):
        sub = argv[i]
        _error(f"{sub} takes none of parent --profile, --patch, --dump-config, or --dump-default-config")

    leftover = list(argv[i:])

    if profile is None:
        if any(a in ("-h", "--help") for a in leftover):
            _help(0)
        _error("--profile <name> is required")

    if profile == "":
        _error("--profile needs a name")

    if any(p == "" for p in patches):
        _error("--patch needs a path")

    if not dump_config and not dump_default_config:
        return {
            "mode": "profile",
            "profile": profile,
            "patches": patches,
            "args": leftover,
        }

    if dump_config and dump_default_config:
        _error("--dump-config and --dump-default-config are mutually exclusive")

    if leftover:
        _error(f"config dumps take no app arguments, got {' '.join(repr(a) for a in leftover)}")

    default_only = bool(dump_default_config)
    if default_only and patches:
        _error("--dump-default-config prints the bundle layers and takes no --patch")

    return {
        "mode": "dump-config",
        "profile": profile,
        "defaultOnly": default_only,
        "patches": patches,
    }


def _parse_web_command(argv: List[str], version: str) -> Dict[str, Any]:
    patches: List[str] = []
    dump_config = False
    dump_default_config = False

    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]

        if tok == "--patch":
            if i + 1 >= n:
                _error("--patch needs a path")
            patches.append(argv[i + 1])
            i += 2
            continue
        elif tok.startswith("--patch="):
            patches.append(tok[len("--patch="):])
            i += 1
            continue

        if tok == "--dump-config":
            dump_config = True
            i += 1
            continue

        if tok == "--dump-default-config":
            dump_default_config = True
            i += 1
            continue

        break

    leftover = list(argv[i:])

    if any(p == "" for p in patches):
        _error("--patch needs a path")

    if not dump_config and not dump_default_config:
        return {
            "mode": "profile",
            "profile": "web",
            "patches": patches,
            "args": leftover,
        }

    if dump_config and dump_default_config:
        _error("--dump-config and --dump-default-config are mutually exclusive")

    if leftover:
        _error(f"config dumps take no app arguments, got {' '.join(repr(a) for a in leftover)}")

    default_only = bool(dump_default_config)
    if default_only and patches:
        _error("--dump-default-config prints the bundle layers and takes no --patch")

    return {
        "mode": "dump-config",
        "profile": "web",
        "defaultOnly": default_only,
        "patches": patches,
    }


def _parse_plugin_command(argv: List[str], version: str) -> Dict[str, Any]:
    profile: Optional[str] = None
    args: List[str] = []

    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]

        if tok == "--profile":
            if i + 1 >= n:
                _error("--profile needs a name")
            profile = argv[i + 1]
            i += 2
            continue
        elif tok.startswith("--profile="):
            profile = tok[len("--profile="):]
            i += 1
            continue

        # Non-flag or forwarded args
        args.append(tok)
        i += 1

    if profile is None:
        _error("--profile <name> is required")
    if profile == "":
        _error("--profile needs a name")
    if not args:
        _error("plugin needs pnpm arguments to forward (e.g. add <package>)")

    return {
        "mode": "plugin",
        "profile": profile,
        "args": args,
    }


# CamelCase alias
parseDshArgs = parse_dsh_args
