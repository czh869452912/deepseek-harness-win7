import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.llm.pi_replay import replay_state, to_pi_assistant
from dsh.llm.pi_stream import to_stream_chunks
from dsh.core.abort import AbortController


async def main():
    rows = []
    for fixture in json.loads((ROOT / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8')):
        row = dict(id=fixture['id'])
        try:
            if fixture['kind'] == 'replay':
                row['value'] = replay_state(fixture['message'])
            if fixture['kind'] == 'assistant':
                degraded = []
                row['value'] = dict(message=to_pi_assistant(fixture['message'], degraded.append), degraded=len(degraded))
            if fixture['kind'] == 'stream':
                row['value'] = []
                controller = AbortController()
                if fixture.get('aborted'):
                    controller.abort()
                async def events():
                    for event in fixture['events']:
                        yield event
                async for chunk in to_stream_chunks(events(), fixture.get('contextWindow'), controller.signal):
                    row['value'].append(chunk)
        except Exception as error:
            row['error'] = dict(code=getattr(error, 'code', type(error).__name__))
        rows.append(row)
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
