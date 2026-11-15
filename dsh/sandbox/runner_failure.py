"""Evidence-based failure classification shared by process sandbox consumers."""
import errno
import os


def runner_failure(code, stderr, rules):
    if code is None or code == 0:
        return None
    for rule in rules:
        if 'allowedExitCodes' in rule and code not in rule['allowedExitCodes']:
            continue
        ignored = {line.lower() for line in rule.get('informationalLines', [])}
        signatures = [value.lower() for value in rule['fatalSignatures'] if value.strip()]
        for line in stderr.split('\n'):
            line = line[:-1] if line.endswith('\r') else line
            if line.lower() not in ignored and any(value in line.lower() for value in signatures):
                return line
    return None


def spawn_runner_failure(error, program, cwd):
    # Popen exposes filename on POSIX; Windows omits the failed executable.
    return (isinstance(error, OSError) and error.errno in (errno.ENOENT, errno.EACCES)
            and os.path.isdir(cwd) and os.access(cwd, os.X_OK)
            and (error.filename == program or (os.name == 'nt' and error.filename is None)))
