"""The sole executable entry: parse launcher options, then boot a profile."""
import asyncio
import sys

from dsh import __version__

from apps.cli.args import parse_dsh_args
from dsh.boot.app_boot import load_layered_env
from dsh.boot.profile_boot import run_profile
from dsh.boot.dump_config import run_dump_config


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        invocation = parse_dsh_args(sys.argv[1:], __version__)
        if invocation["mode"] == "dump-config":
            sys.stdout.write(run_dump_config(invocation["profile"], invocation["defaultOnly"], invocation["patches"]))
            return
        if invocation["mode"] == "plugin":
            from apps.cli.plugin import run_plugin
            raise SystemExit(run_plugin(invocation["profile"], invocation["args"]))
        result = asyncio.run(run_profile({
            "environment": load_layered_env("dsh"),
            "profile": invocation["profile"],
            "patchFiles": invocation["patches"],
            "args": invocation["args"],
        }))
        raise SystemExit(result["shutdown"].exit_code)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (RuntimeError, ValueError, OSError) as error:
        sys.stderr.write("dsh: {}\n".format(error))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
