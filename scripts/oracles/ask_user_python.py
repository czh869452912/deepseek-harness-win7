import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.interaction.user_questions import UserQuestionsPlugin
from dsh.interaction.tool_ask_user import ToolAskUserPlugin


async def main():
    rows = []
    owner = Context()
    try:
        await owner.plugin(SystemPrompt)
        await owner.plugin(ToolsPlugin)
        await owner.plugin(ToolAskUserPlugin)
        rows.append(dict(name='before-questions', schemas=owner.tools.schemas()))
        questions = await owner.plugin(UserQuestionsPlugin)
        definition = owner.tools.get_tool('ask_user_question')
        rows.append(dict(name='with-questions', schema=owner.tools.schemas()[0], outputSchema=definition.output['schema']))
        await questions.dispose()
        await asyncio.sleep(0)
        rows.append(dict(name='questions-disposed', schemas=owner.tools.schemas()))
    finally:
        await owner.fiber.dispose()
    for name in ('answers', 'empty-questions', 'no-provider', 'pre-aborted', 'provider-aborted', 'custom-null', 'selected-invalid', 'question-extra'):
        ctx = Context()
        controller = AbortController()
        requests = []
        try:
            await ctx.plugin(SystemPrompt)
            await ctx.plugin(ToolsPlugin)
            await ctx.plugin(UserQuestionsPlugin)
            await ctx.plugin(ToolAskUserPlugin)

            async def answer(request, next_fn=None):
                body = {key: value for key, value in request.items() if key not in ('signal', 'agent')}
                signal = request.get('signal')
                body.update(signalPresent=signal is not None, signalAborted=bool(signal and signal.aborted), agentPresent='agent' in request)
                requests.append(body)
                if name == 'provider-aborted':
                    controller.abort(RuntimeError('question cancelled'))
                    raise RuntimeError('question cancelled')
                if name == 'custom-null':
                    return dict(answers=[dict(id='choice', selected=[], custom=None)])
                if name == 'selected-invalid':
                    return dict(answers=[dict(id='choice', selected=[7])])
                return dict(answers=[dict(id='choice', selected=['A', 'B'], custom='中文🙂', extra='not projected'), dict(id='notes', selected=[])])

            if name != 'no-provider':
                ctx.on('user-questions/request', answer)
            if name == 'pre-aborted':
                controller.abort(RuntimeError('question cancelled'))
            questions = [] if name == 'empty-questions' else [dict(id='choice', question='Choose?', header='选择', multi_select=True,
                options=[dict(label='A', description='First', extra='retained option'), dict(label='B')], extra='not projected')]
            result = await ctx.tools.execute(ToolExecutionInput('controlled-question', 'ask_user_question',
                dict(questions=questions, extra='accepted'), signal=controller.signal))
            public = dict(content=result.content, isError=result.is_error)
            if not result.is_error:
                public['value'] = result.value
            if result.error is not None:
                public['error'] = result.error
            if result._meta_present:
                public['meta'] = result.meta
            if result.additional_contexts:
                public['additionalContexts'] = result.additional_contexts
            if result.concludes_turn:
                public['concludesTurn'] = True
            rows.append(dict(name=name, requests=requests, result=public))
        finally:
            await ctx.fiber.dispose()
    imports = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            imports[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(ROOT), python=sys.version, executable=sys.executable, imports=imports, rows=rows,
            fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), stream, indent=2)
        stream.write('\n')


asyncio.run(main())
