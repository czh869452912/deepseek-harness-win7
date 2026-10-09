"""Public tool failures preserve JavaScript thrown values and typed error identity."""
import pytest

from dsh.cordis.context import Context
from dsh.cordis.errors import ThrownValueError
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolExecutionInput, ToolsPlugin
from dsh.llm.error import HarnessError
from dsh.llm.llm_service import LlmError
from dsh.fs.fs_local import FsError
from dsh.goal.service import GoalError
from dsh.subagent.errors import SubagentError
from dsh.attachment.error import AttachmentError


VALUES = [
    (None, 'null'), (False, 'false'), (True, 'true'), (0, '0'), (-1, '-1'),
    (1.25, '1.25'), ('', ''), ('text', 'text'), ({}, '[object Object]'),
    ({'kind': 'user'}, '[object Object]'), ({'message': 'denied'}, 'denied'),
    ({'message': ''}, ''), ({'message': 4}, '[object Object]'),
    ({'code': 'FOREIGN', 'name': 'Object'}, '[object Object]'),
    ([], ''), ([None, 0, False, 'x'], ',0,false,x'),
]


def thrown_value(kind, value):
    if kind == 'value':
        return ThrownValueError(value)
    if kind == 'cycle-array':
        cycle = []
        cycle.append(cycle)
        return ThrownValueError(cycle)
    if kind == 'bad-string':
        def hostile():
            raise RuntimeError('hostile')
        return ThrownValueError({'toString': hostile})
    if kind in ('getter-throws', 'getter-attribute-error'):
        class Hostile:
            @property
            def message(self):
                raise (AttributeError('hostile') if kind == 'getter-attribute-error' else RuntimeError('hostile'))
        return ThrownValueError(Hostile())
    if kind == 'typed-error':
        return HarnessError('typed value', 'CONTROLLED_TYPED')
    constructors = dict(fs=FsError, goal=GoalError, subagent=SubagentError, llm=LlmError, attachment=AttachmentError)
    if kind in constructors:
        return constructors[kind]('typed value', 'CONTROLLED_TYPED')
    error = RuntimeError('foreign error' if kind == 'foreign-coded-error' else 'initial')
    if kind == 'foreign-coded-error':
        error.name = 'ForeignError'
        error.code = 'FOREIGN'
    else:
        error.message = 4
    return error


CASES = [('value', value, message) for value, message in VALUES] + [
    ('cycle-array', None, ''), ('bad-string', None, '<unprintable thrown value>'),
    ('getter-throws', None, '<unprintable thrown value>'),
    ('error-number-message', None, 4), ('typed-error', None, 'typed value'),
    ('foreign-coded-error', None, 'foreign error'),
    ('getter-attribute-error', None, '<unprintable thrown value>'),
] + [
    (kind, None, 'typed value') for kind in ('fs', 'goal', 'subagent', 'llm', 'attachment')
]


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,value,message', CASES, ids=[
    'value-' + str(index) for index in range(len(VALUES))
] + [case[0] for case in CASES[len(VALUES):]])
async def test_actual_tool_body_public_error(kind, value, message):
    ctx = Context()
    calls = []
    try:
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)

        async def execute(arguments, execution):
            calls.append(arguments)
            raise thrown_value(kind, value)

        ctx.tools.register(dict(name='probe', description='Controlled thrown value.',
            parameters=dict(type='object', properties={}), execute=execute,
            output=dict(schema=dict(type='string'), render=lambda arguments, result: [])))
        result = await ctx.tools.execute(ToolExecutionInput('call', 'probe', {}, signal=AbortController().signal))
        expected = dict(message=message)
        if kind == 'typed-error':
            expected['info'] = dict(name='HarnessError', code='CONTROLLED_TYPED')
        elif kind in ('fs', 'goal', 'subagent', 'llm'):
            expected['info'] = dict(name=dict(fs='FsError', goal='GoalError', subagent='SubagentError', llm='LlmError')[kind], code='CONTROLLED_TYPED')
        assert calls == [{}]
        assert result.is_error is True
        assert result.error == expected
        assert result.content == [dict(type='text', text='Error: ' + str(message))]
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_tool_body_cancel_preserves_original_reason():
    ctx = Context()
    controller = AbortController()
    try:
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)

        async def execute(arguments, execution):
            controller.abort(dict(kind='user'))
            execution.signal.throwIfAborted()

        ctx.tools.register(dict(name='cancel', description='Controlled cancellation.',
            parameters=dict(type='object', properties={}), execute=execute,
            output=dict(schema=dict(type='string'), render=lambda arguments, result: [])))
        result = await ctx.tools.execute(ToolExecutionInput('call', 'cancel', {}, signal=controller.signal))
        assert result.is_error is True
        assert result.error == dict(message='[object Object]')
        assert result.content == [dict(type='text', text='Error: [object Object]')]
    finally:
        await ctx.fiber.dispose()
