import json
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentRegistry, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.core.tools import ToolsPlugin, ToolsService
from dsh.interaction.tool_ask_user import ToolAskUserPlugin
from dsh.interaction.user_questions import UserQuestionsPlugin, UserQuestionService, UserQuestionError


async def setup():
    ctx = Context()
    tools_plugin = ToolsPlugin()
    tools_plugin.apply(ctx)
    agent_plugin = AgentPlugin()
    agent_plugin.apply(ctx)
    session_plugin = SessionPlugin()
    session_plugin.apply(ctx)
    uq_plugin = UserQuestionsPlugin()
    uq_plugin.apply(ctx)
    tau_plugin = ToolAskUserPlugin()
    tau_plugin.apply(ctx)
    return ctx


@pytest.mark.asyncio
async def test_registers_model_facing_tool_schema():
    ctx = await setup()
    tools_svc = ctx.get('tools')
    schemas = tools_svc.schemas()
    schema = next((s for s in schemas if s['name'] == 'ask_user_question'), None)
    assert schema is not None
    assert schema['name'] == 'ask_user_question'
    params = schema['parameters']
    assert params['type'] == 'object'
    assert 'questions' in params['properties']
    q_props = params['properties']['questions']['items']['properties']
    assert 'id' in q_props
    assert 'question' in q_props
    assert 'options' in q_props
    assert 'multi_select' in q_props


@pytest.mark.asyncio
async def test_asks_registered_user_questions_provider_and_projects_answers():
    ctx = await setup()
    seen = []

    class MockAnswerer:
        async def ask(self, req):
            seen.append(req)
            return {'answers': [{'id': 'pkg', 'selected': ['pnpm']}]}

    ctx.on('user-questions/request', lambda req, next_fn=None: MockAnswerer().ask(req))

    tools_svc = ctx.get('tools')
    result = await tools_svc.execute({
        'callId': 'ask-1',
        'name': 'ask_user_question',
        'arguments': {
            'questions': [{
                'id': 'pkg',
                'question': 'Which package manager should I use?',
                'options': [{'label': 'pnpm', 'description': 'Use pnpm workspaces.'}],
            }],
        },
    })

    assert result.is_error is False
    data = json.loads(result.content[0]['text'])
    assert data == {'answers': [{'id': 'pkg', 'selected': ['pnpm']}]}
    assert len(seen) == 1
    assert seen[0]['questions'][0]['id'] == 'pkg'


@pytest.mark.asyncio
async def test_projects_custom_answers_and_multi_select():
    ctx = await setup()

    class MockAnswerer:
        async def ask(self, req):
            return {
                'answers': [
                    {'id': 'targets', 'selected': ['tests', 'docs'], 'custom': 'release notes'},
                    {'id': 'labels-only', 'selected': ['tests']},
                    {'id': 'notes', 'selected': [], 'custom': 'ship today'},
                ]
            }

    ctx.on('user-questions/request', lambda req, next_fn=None: MockAnswerer().ask(req))

    tools_svc = ctx.get('tools')
    result = await tools_svc.execute({
        'callId': 'ask-multi',
        'name': 'ask_user_question',
        'arguments': {
            'questions': [
                {'id': 'targets', 'question': 'What should I update?', 'options': [{'label': 'tests'}, {'label': 'docs'}], 'multi_select': True},
                {'id': 'labels-only', 'question': 'Which labels should I keep?', 'options': [{'label': 'tests'}, {'label': 'docs'}], 'multi_select': True},
                {'id': 'notes', 'question': 'Any note?'},
            ],
        },
    })

    assert result.is_error is False
    data = json.loads(result.content[0]['text'])
    assert data['answers'][0] == {'id': 'targets', 'selected': ['tests', 'docs'], 'custom': 'release notes'}
    assert data['answers'][1] == {'id': 'labels-only', 'selected': ['tests']}
    assert data['answers'][2] == {'id': 'notes', 'selected': [], 'custom': 'ship today'}


@pytest.mark.asyncio
async def test_returns_structured_user_questions_errors_no_provider():
    ctx = await setup()
    tools_svc = ctx.get('tools')
    result = await tools_svc.execute({
        'callId': 'ask-no-provider',
        'name': 'ask_user_question',
        'arguments': {'questions': [{'id': 'continue', 'question': 'Continue?'}]},
    })

    assert result.is_error is True
    assert result.error['info']['name'] == 'UserQuestionError'
    assert result.error['info']['code'] == 'NO_PROVIDER'


@pytest.mark.asyncio
async def test_rejects_delegated_caller_with_structured_error():
    ctx = await setup()
    agents = ctx.get('agents')
    store = ctx.get('sessions')

    sess_root = store.create('root')
    agent_root = Agent(agent_id='root', session=sess_root, ctx=ctx)
    agents.enter(agent_root)

    sess_child = store.create('child')
    agent_child = Agent(agent_id='child', session=sess_child, ctx=ctx)
    agents.enter(agent_child, owner=agent_root)

    tools_svc = ctx.get('tools')
    result = await tools_svc.execute({
        'callId': 'ask-delegated',
        'name': 'ask_user_question',
        'arguments': {'questions': [{'id': 'continue', 'question': 'Continue?'}]},
        'agent': agent_child,
    })

    assert result.is_error is True
    assert result.error['info']['name'] == 'UserQuestionError'
    assert result.error['info']['code'] == 'DELEGATED_CALLER'


@pytest.mark.asyncio
async def test_returns_structured_error_for_empty_questions():
    ctx = await setup()
    tools_svc = ctx.get('tools')
    result = await tools_svc.execute({
        'callId': 'ask-empty',
        'name': 'ask_user_question',
        'arguments': {'questions': []},
    })

    assert result.is_error is True
    assert result.error['info']['name'] == 'UserQuestionError'
    assert result.error['info']['code'] == 'EMPTY_QUESTIONS'