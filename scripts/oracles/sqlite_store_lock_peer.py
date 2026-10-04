import argparse
import json
from pathlib import Path
import sys

ROOT = Path(sys.argv[sys.argv.index('--root') + 1]).resolve() if '--root' in sys.argv else Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.session.sqlite_database import SqliteDatabase

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path)
parser.add_argument('--path', required=True)
parser.add_argument('--mode', choices=('hold', 'append'), required=True)
args = parser.parse_args()
database = SqliteDatabase(args.path)
try:
    database.exec('BEGIN IMMEDIATE')
    if args.mode == 'append':
        database.prepare('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)').run(1, 1, 'turn/end', 1, '{"turn":1}', None, None, 0)
        database.exec('UPDATE sessions SET revision=revision+1')
        database.exec('COMMIT')
        print(json.dumps(dict(appended=True)), flush=True)
    else:
        print(json.dumps(dict(held=True)), flush=True)
        sys.stdin.readline()
        database.exec('ROLLBACK')
finally:
    database.close()
