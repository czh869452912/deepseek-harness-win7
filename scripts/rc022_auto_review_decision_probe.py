"""Differential closed review protocol and terminal stream validation."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def text_chunks(text, kind='text', index=0):
    return [dict(type='block-start', index=index, blockType=kind),
            dict(type=kind + '-delta', index=index, text=text[:7]),
            dict(type=kind + '-delta', index=index, text=text[7:]),
            dict(type='block-end', index=index, block=dict(type=kind, text=text))]


def corpus():
    rows = []
    for risk in ('low', 'medium', 'high', 'unknown', None, [], True):
        for decision in ('allow', 'deny', None):
            for reason in (None, '', 'raw:\n\"secret\" 🐱', 1):
                value = dict(risk=risk, decision=decision)
                if reason is not None:
                    value['reason'] = reason
                rows.append(dict(name='json-%d' % len(rows), text=json.dumps(value, ensure_ascii=False)))
    for text in ('null', '[]', '"text"', 'false', '1', '{}', '{"decision":"allow"}',
                 '{"risk":"medium","risk":"high","decision":"deny"}',
                 '{"risk":"high","decision":"deny","reason":"one","reason":"two"}',
                 '{"risk":"high","decision":"deny","r\\u0065ason":"one","reason":"two"}',
                 '{"risk":"high","decision":"deny","extra":[{"nested":true}]}',
                 '{"risk":"high","decision":"deny","reason":"colon: braces{} [] quote\\\""}',
                 'not json', '', '```json\n{}\n```', '{"risk":NaN,"decision":"allow"}',
                 '{"risk":"low","decision":"allow"} trailing'):
        rows.append(dict(name='json-%d' % len(rows), text=text))
    good = '{"risk":"low","decision":"allow"}'
    body = text_chunks(good)
    stop = dict(type='finish', reason=dict(kind='stop'))
    streams = {
        'valid': body + [stop], 'reasoning': text_chunks('private', 'reasoning', 8) + body + [stop],
        'reasonings': text_chunks('a', 'reasoning', 9) + text_chunks('b', 'reasoning', 4) + body + [stop],
        'absent-finish': body, 'empty': [], 'stop-only': [stop],
        'double-finish': body + [stop, stop], 'after-finish': body + [stop, dict(type='usage', usage={})],
        'late-reasoning': body + text_chunks('private', 'reasoning', 1) + [stop],
        'two-texts': body + text_chunks('{}', index=1) + [stop],
        'reasoning-only': text_chunks('private', 'reasoning') + [stop],
        'whitespace-text': text_chunks(' \n ') + [stop],
        'unknown-index-text': [dict(type='text-delta', index=42, text=good), stop],
        'end-authoritative': [dict(type='block-start', index=0, blockType='text'),
                              dict(type='text-delta', index=0, text='invalid delta'),
                              dict(type='block-end', index=0, block=dict(type='text', text=good)), stop],
        'delta-after-end': body + [dict(type='text-delta', index=0, text='ignored'), stop],
        'tool': [dict(type='block-end', index=0, block=dict(type='tool-call', id='id', name='probe', arguments='{}')), stop],
        'image': [dict(type='block-end', index=0, block=dict(type='image', attachment={})), stop],
        'provider-failure': body,
    }
    for kind in ('max-tokens', 'tool-calls', 'error', 'aborted'):
        reason = dict(kind=kind)
        if kind in ('error', 'aborted'):
            reason['failure'] = dict(code='UNKNOWN', message='provider secret')
        streams[kind] = body + [dict(type='finish', reason=reason)]
    rows += [dict(name='stream-' + name, chunks=chunks, fail=name == 'provider-failure') for name, chunks in streams.items()]
    for reason in (None, '', 'raw:\n秘密 🐱'):
        row = dict(name='present-%d' % len(rows), present=True)
        if reason is not None:
            row['reason'] = reason
        rows.append(row)
    return rows


async def observe():
    from dsh.core.session.json import UNDEFINED
    from dsh.interaction.auto_review_decision import parse_decision, read_decision, denied, ask_user, failed
    rows = []
    for case in corpus():
        error = RuntimeError('provider secret')
        closed = []
        async def stream():
            try:
                for chunk in case['chunks']:
                    yield chunk
                if case.get('fail'):
                    raise error
            finally:
                closed.append(True)
        try:
            if case.get('present'):
                reason = case.get('reason', UNDEFINED)
                result = dict(denied=denied('probe', reason), ask=ask_user('probe', reason), failed=failed('probe', error))
            else:
                result = dict(value=await read_decision(stream()) if 'chunks' in case else parse_decision(case['text']))
        except ValueError:
            result = dict(error=dict(syntax=True))
        except Exception as failure:
            result = dict(error=dict(message=str(failure), original=failure is error))
        row = dict(name=case['name'], result=result)
        if 'chunks' in case:
            row['closed'] = closed == [True]
        rows.append(row)
    return rows


def prepare(output):
    path = output/'corpus.json'
    path.write_text(json.dumps(corpus(), ensure_ascii=False), encoding='utf-8')
    return [path]


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_auto_review_decision.mts', 'Closed Auto review JSON and streamed block/finish protocol, duplicate members, six legal combinations, exact semantic failures, provider error identity and denial/ask/failure presentation. JSON syntax error wording is runtime-specific and compared by rejection only.',
               [Path(__file__).resolve(), ROOT/'dsh/interaction/auto_review_decision.py', ROOT/'dsh/llm/assembler.py'], prepare=prepare)
