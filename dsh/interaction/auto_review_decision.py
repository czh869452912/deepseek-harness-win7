"""Closed Auto review protocol from pinned dsh 0.2.2-rc.3.

This module does not install or enable Auto. The integration owns the stream,
Session snapshot, cancellation and permission contribution.
"""
import json
import re

from dsh.core.session.json import UNDEFINED
from dsh.llm.assembler import BlockAssembler


def _member_count(text):
    syntax = re.sub(r'"(?:\\.|[^"\\])*"', '', text, flags=re.S)
    depth = count = 0
    for char in syntax:
        if char in '{[':
            depth += 1
        elif char in '}]':
            depth -= 1
        elif char == ':' and depth == 1:
            count += 1
    return count


def parse_decision(text):
    def reject_constant(value):
        raise ValueError('Invalid JSON numeric constant: ' + value)
    value = json.loads(text, parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise RuntimeError('auto-review: reviewer output must be one JSON object')
    if _member_count(text) != len(value):
        raise RuntimeError('auto-review: reviewer output repeats a JSON member')
    risk, decision = value.get('risk'), value.get('decision')
    if len(value) == 2:
        if decision == 'allow' and risk in ('low', 'medium'):
            return dict(risk=risk, decision=decision)
        if decision == 'deny' and risk in ('medium', 'high'):
            return dict(risk=risk, decision=decision)
    if (len(value) == 3 and decision == 'deny' and risk in ('medium', 'high')
            and isinstance(value.get('reason'), str)):
        return dict(risk=risk, decision=decision, reason=value['reason'])
    raise RuntimeError('auto-review: reviewer output does not match the risk/decision protocol')


async def read_decision(stream):
    assembler = BlockAssembler()
    finished = False
    try:
        async for chunk in stream:
            if finished:
                raise RuntimeError('auto-review: reviewer emitted data after its terminal finish')
            assembler.push(chunk)
            if chunk['type'] == 'finish':
                finished = True
                reason = chunk['reason']
                if reason['kind'] in ('error', 'aborted'):
                    failure = reason['failure']
                    raise RuntimeError('auto-review: reviewer ended with %s %s: %s' %
                                       (reason['kind'], failure['code'], failure['message']))
                if reason['kind'] != 'stop':
                    raise RuntimeError('auto-review: reviewer ended with ' + reason['kind'])
    except BaseException:
        # JS for-await closes its iterator when the loop body rejects. Preserve
        # the original failure even if the producer's close itself fails.
        close = getattr(stream, 'aclose', None)
        if close is not None:
            try:
                await close()
            except BaseException:
                pass
        raise
    if not finished:
        raise RuntimeError('auto-review: reviewer emitted no terminal finish')
    blocks = assembler.blocks()
    if not blocks or blocks[-1]['type'] != 'text' or any(block['type'] != 'reasoning' for block in blocks[:-1]):
        raise RuntimeError('auto-review: reviewer must emit zero or more reasoning blocks followed by exactly one text block')
    return parse_decision(blocks[-1]['text'])


_DENIED = {
    'en': ('Auto review denied this call.', 'Auto review denied this call: '),
    'zh': ('Auto review 拒绝了此调用。', 'Auto review 拒绝了此调用：'),
    'ja': ('自動認可レビューがこの呼び出しを拒否しました。', '自動認可レビューがこの呼び出しを拒否しました：'),
    'es': ('Auto review ha denegado esta llamada.', 'Auto review ha denegado esta llamada: '),
    'fr': ('Auto review a refusé cet appel.', 'Auto review a refusé cet appel : '),
    'de': ('Auto review hat diesen Aufruf abgelehnt.', 'Auto review hat diesen Aufruf abgelehnt: '),
    'ru': ('Auto review отклонила этот вызов.', 'Auto review отклонила этот вызов: '),
    'pt': ('Auto review negou esta chamada.', 'Auto review negou esta chamada: '),
}


def denied(name, reason=UNDEFINED):
    info = dict(name='AutoReviewDeniedError', code='AUTO_REVIEW_DENIED')
    if reason is not UNDEFINED:
        info['reason'] = reason
    return dict(kind='deny', reason='Auto review rejected tool "%s"; its body was not executed' % name, info=info)


def ask_user(name, reason=UNDEFINED):
    denial = 'Auto review denied tool "%s"' % name
    return dict(kind='ask', reason=denial if reason is UNDEFINED else denial + ': ' + reason,
                displayReason={locale: texts[0] if reason is UNDEFINED else texts[1] + reason for locale, texts in _DENIED.items()})


def failed(name, error):
    return dict(kind='deny', reason='Auto review of tool "%s" failed; its body was not executed: %s' % (name, str(error)),
                info=dict(name='AutoReviewFailedError', code='AUTO_REVIEW_FAILED'))
