import asyncio
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.llm.pi_replay import replay_state, to_pi_assistant
from dsh.llm.pi_stream import to_stream_chunks
from dsh.llm.pi_context import to_pi_context, to_pi_context_with_images
from dsh.llm.pi_config import resolve_profiles
from dsh.llm.pi_model import model_info
from dsh.llm.pi_transform import transform_messages
from dsh.core.abort import AbortController


async def main():
    rows = []
    for fixture in json.loads((ROOT / 'scripts/oracles/pi-fixtures.json').read_text(encoding='utf-8')):
        row = dict(id=fixture['id'])
        try:
            if fixture['kind'] == 'transform':
                row['value'] = transform_messages(fixture['messages'], fixture['model'],
                    (lambda identity, _model, _message: identity.replace('|', '_')) if fixture.get('normalize') else None,
                    now=lambda: 123)
            if fixture['kind'] == 'catalog':
                row['value'] = []
                for identity, profile in resolve_profiles(fixture.get('providers')).items():
                    row['value'].append(dict(id=identity, info=[model_info(profile, model['id']) for model in profile['models']],
                        **{key: profile[key] for key in ('displayName', 'models', 'configuredMaxTokens',
                           'streamIdleTimeoutMs', 'maxRequestImageBytes', 'requestImagePixelBudget', 'requestImageMaxBytes', 'retryPolicy')}))
            if fixture['kind'] == 'context':
                degraded, reads = [], []
                if 'images' in fixture:
                    class Store:
                        def read_image_request(self, ref, policy, signal):
                            reads.append(dict(id=ref['attachmentId'], policy=policy))
                            version = fixture['images'][ref['attachmentId']]
                            return dict(version, data=base64.b64decode(version['data']))
                    context = await to_pi_context_with_images(fixture['options'], Store(),
                        lambda ref: fixture.get('access', {}).get(ref['attachmentId']),
                        fixture.get('maxBytes'), fixture.get('policy'), degraded.append)
                else:
                    context = to_pi_context(fixture['options'], degraded.append)
                row['value'] = dict(context=context, degraded=len(degraded), reads=reads)
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
            row['error'] = dict(code='Error' if fixture['kind'] == 'catalog' and isinstance(error, ValueError)
                               else getattr(error, 'code', type(error).__name__))
        rows.append(row)
    Path(sys.argv[1]).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
