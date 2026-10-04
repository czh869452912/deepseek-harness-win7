import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main():
    mode = sys.argv[1]
    if mode == 'descendant':
        signal.signal(signal.SIGTERM, lambda signum, frame: None)
        while True:
            time.sleep(1)
    state_path = Path(sys.argv[2])
    descendant = subprocess.Popen([sys.executable, __file__, 'descendant'],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
    signal.signal(signal.SIGTERM, lambda signum, frame: None)
    pending = state_path.with_suffix('.pending')
    pending.write_text(json.dumps({'root': os.getpid(), 'descendant': descendant.pid,
                                  'cwd': os.getcwd()}), encoding='utf-8')
    pending.replace(state_path)
    while True:
        time.sleep(1)


if __name__ == '__main__':
    main()
