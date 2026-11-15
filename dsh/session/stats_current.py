"""rc3 whole-log statistics over embedded Assistant streams."""
import math

from dsh.core.session.json import UNDEFINED
from dsh.cordis.plugin import Plugin
from dsh.llm.assistant_stream import assistantStreamFirstTokenTime
from dsh.session.stats import init_session_stats, view_session_stats


TOTALS = ('turns', 'steps', 'llmMs', 'toolMs', 'ttftMs', 'ttftSteps', 'decodeMs', 'decodeTokens')


def _number(value, integer=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or integer and int(value) != value:
        raise ValueError('sessionStats: expected a nonnegative finite ' + ('integer' if integer else 'number'))
    return value


def parse_stats_view(value):
    if not isinstance(value, dict) or set(value) != set(TOTALS):
        raise ValueError('sessionStats: invalid totals keys')
    return {key: _number(value[key], key in ('turns', 'steps', 'ttftSteps')) for key in TOTALS}


def parse_stats_state(value):
    if not isinstance(value, dict) or set(value) != set(TOTALS) | {'lastTurn', 'openStep', 'pendingCalls'}:
        raise ValueError('sessionStats: invalid state keys')
    result = parse_stats_view({key: value[key] for key in TOTALS})
    result['lastTurn'] = None if value['lastTurn'] is None else _number(value['lastTurn'], True)
    opened = value['openStep']
    if opened is not None:
        if not isinstance(opened, dict):
            raise ValueError('sessionStats: invalid openStep')
        opened = {key: None if key == 'firstTokenTime' and opened[key] is None else _number(opened[key], key in ('turn', 'step'))
                  for key in ('turn', 'step', 'startTime', 'firstTokenTime')}
    result['openStep'] = opened
    calls = value['pendingCalls']
    if not isinstance(calls, dict) or any(not isinstance(key, str) for key in calls):
        raise ValueError('sessionStats: invalid pendingCalls')
    result['pendingCalls'] = {key: _number(time) for key, time in calls.items()}
    return result


def _first(stream):
    value = assistantStreamFirstTokenTime(stream)
    return None if value is UNDEFINED else value


def apply_stats(state, event):
    kind, data, time = event['type'], event['data'], event['time']
    if kind == 'step/start':
        return dict(state, openStep=dict(turn=data['turn'], step=data['step'], startTime=time, firstTokenTime=None))
    if kind in ('assistant/attempt', 'assistant/message'):
        opened = state['openStep']
        if opened is None or opened['turn'] != data['turn'] or opened['step'] != data['step']:
            return state
        first = opened['firstTokenTime']
        if kind == 'assistant/attempt':
            stream_first = _first(data['stream'])
            return state if first is not None or stream_first is None else dict(state, openStep=dict(opened, firstTokenTime=stream_first))
        first = first if first is not None else _first(data['stream'])
        result = dict(state, llmMs=state['llmMs'] + max(0, time - opened['startTime']), openStep=None)
        if first is not None:
            result['ttftMs'] += max(0, first - opened['startTime'])
            result['ttftSteps'] += 1
            usage = data.get('usage')
            output = usage.get('outputTokens') if isinstance(usage, dict) else None
            if type(output) in (int, float) and math.isfinite(output) and output >= 0:
                result['decodeMs'] += max(0, time - first)
                result['decodeTokens'] += output
        return result
    if kind == 'tool/call':
        return dict(state, pendingCalls=dict(state['pendingCalls'], **{data['callId']: time}))
    if kind == 'tool/result':
        identity = data['message']['source']['callId']
        if identity not in state['pendingCalls']:
            return state
        pending = dict(state['pendingCalls'])
        dispatched = pending.pop(identity)
        return dict(state, toolMs=state['toolMs'] + max(0, time - dispatched), pendingCalls=pending)
    if kind == 'step/end':
        return dict(state, turns=state['turns'] + (0 if state['lastTurn'] == data['turn'] else 1),
                    steps=state['steps'] + 1, lastTurn=data['turn'], openStep=None)
    if kind == 'turn/end' and state['pendingCalls']:
        return dict(state, pendingCalls={})
    return state


STATS_DEFINITION = dict(key='sessionStats', stateVersion=1, stateSchema=parse_stats_state,
    init=lambda *_: init_session_stats(), apply=apply_stats,
    wire=dict(viewSchema=parse_stats_view, view=view_session_stats,summary=False))


class CurrentSessionStatsPlugin(Plugin):
    id = 'session-stats'
    name = '@deepseek-ai/dsh-session-stats'
    inject = ['sessionProjections']

    async def apply(self, ctx):
        await ctx.get('sessionProjections').register(STATS_DEFINITION)
