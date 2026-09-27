import asyncio
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dsh.core.session import SessionHeader
from dsh.session.persistence_jsonl import JsonlSessionPersistence

async def observe():
    rows = []
    fixtures = json.loads(Path(__file__).with_name('session-recovery-fixtures.json').read_text(encoding='utf-8'))
    for fixture in fixtures:
        with tempfile.TemporaryDirectory() as root:
            p = JsonlSessionPersistence(root)
            meta = SessionHeader.from_dict(dict(id=fixture['mode'], version=0, createdAt=1, delegationDepth=0))
            path = Path(p.locate(meta).path)
            path.parent.mkdir(parents=True, exist_ok=True)
            header = dict(type='session', id=meta.id, version=0, createdAt=1, delegationDepth=0)
            raw = ('\n'.join(json.dumps(e) for e in [header] + fixture['events']) + '\n' + fixture['tail']).encode('utf-8')
            path.write_bytes(raw)
            inspected = await p.inspect(meta.id)
            before = await p.read_from(meta.id, 1)
            untouched = path.read_bytes() == raw
            loaded = await p.load(meta.id)
            again = await p.load(meta.id)
            after = await p.read_from(meta.id, 0)
            rows.append(dict(mode=fixture['mode'], inspected=inspected.events, before=before.events,
                untouched=untouched, loaded=loaded.events, again=again.events, after=after.events))
    return rows

if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observe()), indent=2)+'\n', encoding='utf-8')
