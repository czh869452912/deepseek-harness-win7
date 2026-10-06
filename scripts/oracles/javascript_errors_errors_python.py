from pathlib import Path
import runpy
import sys


sys.argv.extend(['--group', 'errors'])
runpy.run_path(str(Path(__file__).with_name('javascript_errors_observer.py')),run_name='__main__')
