"""Dedicated Win7 ACL runner, with the pinned argv/exit failure contract."""
import argparse
import os
import shutil
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dsh.sandbox.windows_acl import WinApi, assert_temp_outside, capability_sid


class RunnerParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = RunnerParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--temp", required=True)
    parser.add_argument("--mode", required=True, choices=["read-only", "workspace-write"])
    parser.add_argument("--write-sid")
    parser.add_argument("--temp-write-sid")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("missing command after --")
    for path in (args.workspace, args.temp):
        if not os.path.isdir(path):
            raise ValueError("not an existing directory: " + path)
    if bool(args.write_sid) != bool(args.temp_write_sid):
        raise ValueError("workspace and temp SIDs must be supplied together")
    if args.mode == "read-only" and args.write_sid:
        raise ValueError("read-only does not accept capability SIDs")
    api = WinApi()
    private = None
    owned = None
    temp_sid = None
    try:
        sids = []
        if args.mode == "workspace-write":
            assert_temp_outside(args.workspace, args.temp)
            workspace_sid = capability_sid(args.workspace)
            if args.write_sid:
                private = args.temp
                temp_sid = capability_sid(private, True)
                if args.write_sid != workspace_sid or args.temp_write_sid != temp_sid:
                    raise ValueError("capability SID does not match its owning directory")
            else:
                private = owned = tempfile.mkdtemp(prefix="dsh-", dir=args.temp)
                temp_sid = capability_sid(private, True)
                api.grant(args.workspace, workspace_sid)
                api.grant(private, temp_sid)
            sids = [workspace_sid, temp_sid]
            os.environ["TMP"] = os.environ["TEMP"] = private
        with api.restricted_token(sids) as token:
            return api.run(token, command, os.getcwd())
    finally:
        if owned:
            try:
                if temp_sid:
                    api.grant(owned, temp_sid, revoke=True)
            except Exception as error:
                print("windows-acl-run: cleanup: {}".format(error), file=sys.stderr)
            try:
                shutil.rmtree(owned)
            except Exception as error:
                print("windows-acl-run: cleanup: {}".format(error), file=sys.stderr)


if __name__ == "__main__":
    try:
        code = main()
    except BaseException as error:
        print("windows-acl-run: {}".format(error), file=sys.stderr, flush=True)
        code = 127
    # PyLong_AsLong in Python 3.8's SystemExit handling accepts signed LONG.
    # Preserve the DWORD bit pattern instead of overflowing into exit(-1).
    sys.exit(code - 0x100000000 if code >= 0x80000000 else code)
