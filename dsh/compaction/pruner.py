"""Replay-safe tool-result pruning, ported from the pinned upstream package."""

import math
from typing import Any, Dict, List, Optional

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.service import Service
from dsh.cordis.utils import js_to_string
from dsh.core.session.json import deep_freeze

PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"
DEFAULTS = deep_freeze(dict(thresholdChars=8192, headChars=4096, tailChars=1024))


def _code_points(text: str) -> List[str]:
    """JS string iteration: astral characters and explicit surrogate pairs count once."""
    points = []
    index = 0
    while index < len(text):
        size = 1
        if (0xD800 <= ord(text[index]) <= 0xDBFF and index + 1 < len(text)
                and 0xDC00 <= ord(text[index + 1]) <= 0xDFFF):
            size = 2
        points.append(text[index:index + size])
        index += size
    return points


def code_point_length(text: str) -> int:
    return len(_code_points(text))


def resolve_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = {} if config is None else config
    for key in raw:
        if key not in DEFAULTS:
            raise ValueError('ToolResultPruneConfig: unknown key "{}" '
                             '(allowed: thresholdChars, headChars, tailChars)'.format(key))
    resolved = {}
    for key, default in DEFAULTS.items():
        value = raw.get(key)
        if value is None:
            value = default
        minimum = 1 if key == 'thresholdChars' else 0
        valid = type(value) in (int, float)
        if valid:
            try:
                number = float(value)
                valid = math.isfinite(number) and number.is_integer() and number >= minimum
            except OverflowError:
                valid = False
        if not valid:
            raise ValueError('ToolResultPruneConfig: {} ({}) must be a {} integer'.format(
                key, js_to_string(value), 'positive' if minimum else 'non-negative'))
        resolved[key] = number if number == 0 and math.copysign(1, number) < 0 else int(number)
    emitted = float(resolved['headChars']) + code_point_length(PRUNE_MARKER) + float(resolved['tailChars'])
    if emitted > resolved['thresholdChars']:
        raise ValueError('ToolResultPruneConfig: headChars + marker + tailChars ({}) '
                         'must be at most thresholdChars ({})'.format(
                             js_to_string(emitted), js_to_string(resolved['thresholdChars'])))
    return deep_freeze(resolved)


def _python_options(config, threshold_chars, head_chars, tail_chars):
    """Explicit Python keyword arguments adapt to the canonical config keys."""
    raw = dict(config) if config is not None else {}
    for key, value in [('thresholdChars', threshold_chars), ('headChars', head_chars), ('tailChars', tail_chars)]:
        if value is not None:
            raw[key] = value
    return raw


class ToolResultPruner(Service):
    inject = ['tokenMeter']
    Config = Schema.object({
        'thresholdChars': Schema.number().step(1).min(1).default(DEFAULTS['thresholdChars']),
        'headChars': Schema.number().step(1).min(0).default(DEFAULTS['headChars']),
        'tailChars': Schema.number().step(1).min(0).default(DEFAULTS['tailChars']),
    })

    def __init__(self, threshold_chars=None, head_chars=None, tail_chars=None,
                 config=None, ctx=None):
        self.config = resolve_config(_python_options(config, threshold_chars, head_chars, tail_chars))
        if ctx is None:
            self.ctx = None
        else:
            super().__init__(ctx, 'toolResultPruner')

    def measure_content(self, blocks):
        return sum(code_point_length(block['text']) for block in blocks if block['type'] == 'text')

    def prune_content(self, blocks):
        total = self.measure_content(blocks)
        if total <= self.config['thresholdChars']:
            return None
        removed_start = int(self.config['headChars'])
        removed_end = total - int(self.config['tailChars'])
        pruned, consumed, inserted = [], 0, False
        for block in blocks:
            if block['type'] != 'text':
                pruned.append(block)
                continue
            points = _code_points(block['text'])
            end = consumed + len(points)
            head_end = min(len(points), max(0, removed_start - consumed))
            tail_start = min(len(points), max(0, removed_end - consumed))
            intersects = consumed < removed_end and end > removed_start
            marker = PRUNE_MARKER if intersects and not inserted else ''
            if marker:
                inserted = True
            text = ''.join(points[:head_end]) + marker + ''.join(points[tail_start:])
            if text:
                pruned.append(dict(block, text=text))
            consumed = end
        if not inserted:
            raise RuntimeError('tool-result prune: failed to locate the removed text span')
        after = self.measure_content(pruned)
        if after > self.config['thresholdChars'] or after >= total:
            raise RuntimeError('tool-result prune: replacement must be smaller and within threshold')
        return pruned

    def prune_session(self, session):
        candidates = []
        for seq in list(session.surface.nodes):
            event = session.events[seq]
            if event['type'] == 'tool/result':
                candidates.append((seq, event))
        pruned, chars_removed = [], 0
        for seq, event in candidates:
            original = event['data']['message']
            result = original['content'][0]
            content = self.prune_content(result['content'])
            if content is None:
                continue
            before, after = self.measure_content(result['content']), self.measure_content(content)
            message = deep_freeze(dict(original, content=[dict(result, content=content)]))
            session.append('compaction/prune', dict(
                shadowedRange=dict(start=seq, end=seq), shadowedSeqs=[seq],
                shadowedTokenCount=self.ctx.get('tokenMeter').estimate_message(original)))
            replacement = session.append('tool/result', dict(event['data'], message=message),
                surface_op=dict(op='replace', start=seq, end=seq), source_event_seqs=[seq])
            pruned.append(dict(originalSeq=seq, replacementSeq=replacement['seq'],
                callId=original['source']['callId'], charsBefore=before, charsAfter=after))
            chars_removed += before - after
        return dict(pruned=pruned, charsRemoved=chars_removed)

    measureContent = measure_content
    pruneContent = prune_content
    pruneSession = prune_session


class ToolResultPrunerPlugin(Plugin):
    id = 'tool-result-pruner'
    name = '@deepseek-ai/dsh-compaction-tool-result-pruner'
    inject = ['tokenMeter']
    Config = ToolResultPruner.Config

    def __init__(self, config=None, threshold_chars=None, head_chars=None, tail_chars=None):
        super().__init__(_python_options(config, threshold_chars, head_chars, tail_chars))

    def apply(self, ctx):
        ToolResultPruner(config=self.config, ctx=ctx)


codePointLength = code_point_length
resolveConfig = resolve_config
