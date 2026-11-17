"""Bundled Office skill provider; files remain the pinned upstream resources."""
import asyncio
import os
import re
import warnings
from pathlib import Path
from types import SimpleNamespace

from ruamel.yaml import YAML
from ruamel.yaml.constructor import SafeConstructor

from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema
from dsh.cordis.text import trim_js
from dsh.core.abort import abort_reason_error
from dsh.core.cancellation import aborted
from dsh.core.cleanup import CleanupPromise
from dsh.skill.registry import wait_with_abort

NAMES = ['office', 'office-docx', 'office-pptx', 'office-xlsx']
ASSETS = Path(__file__).resolve().parents[2] / 'packages/skill/skill-office/assets'
PYTHON_ENVIRONMENTS = {
    'workspace-dependencies': 'Follow an explicit user or applicable AGENTS.md requirement for a Python environment. Otherwise call `load_workspace_dependencies` and run scripts with its Python executable and bundled libraries. Do not install packages or search for a system Python for the default workflow. If the tool is unavailable, use an already configured environment and report a missing dependency only when it prevents the requested operation.',
    'user': "Follow an explicit user or applicable AGENTS.md requirement for a Python environment. Otherwise use the project's or user's existing Python, such as `python3` or `python` on PATH. Before the first script, check that this Python can import the libraries the workflow needs. If Python or a library is missing, tell the user which packages to install; do not install packages into a global environment without the user's agreement.",
}


class _CoreConstructor(SafeConstructor):
    def flatten_mapping(self, node):
        # yaml@2 defaults to YAML 1.2 core: << is an ordinary string key.
        for key, _value in node.value:
            if key.tag == 'tag:yaml.org,2002:merge':
                key.tag = 'tag:yaml.org,2002:str'


_CoreConstructor.add_constructor('tag:yaml.org,2002:timestamp', SafeConstructor.construct_scalar)


def _parse(raw, path):
    match = re.match(r'^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)', raw)
    if match is None:
        raise ValueError('skill-office: ' + path + ' has no YAML frontmatter')
    parser = YAML(typ='safe', pure=True)
    parser.Constructor = _CoreConstructor
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        metadata = parser.load(match.group(1))
    description = metadata.get('description') if isinstance(metadata, dict) else None
    if not isinstance(description, str) or not description:
        raise ValueError('skill-office: ' + path + ' has no description')
    return dict(description=description, content=trim_js(raw[match.end():]))


def _read_file(path):
    with open(path, 'rb') as stream:
        return stream.read().decode('utf-8', 'replace')


class CurrentOfficeSkills(Plugin):
    name = 'skill-office'
    inject = ['skills']
    Config = Schema.object(dict(assetRoot=Schema.string().min(1),
        pythonEnvironment=Schema.union(['workspace-dependencies', 'user']).default('workspace-dependencies')))

    def apply(self, ctx):
        root = self.config.get('assetRoot') or str(ASSETS)
        if not os.path.isabs(root):
            raise ValueError('skill-office: assetRoot must be an absolute directory')
        reported, workers = {}, set()

        async def drain():
            if workers:
                await asyncio.gather(*(asyncio.shield(work) for work in list(workers)), return_exceptions=True)
        ctx.effect(lambda: drain)

        def failed(name, error, persistent):
            failure = str(error)
            if reported.get(name) != failure:
                reported[name] = failure
                ctx.logger.warn('skill-office: skill "' + name + '" is unavailable: ' + failure)
            return dict(kind='failed', error=error, persistent=persistent)

        async def read(name, signal):
            path = os.path.join(root, name, 'SKILL.md')
            try:
                if aborted(signal):
                    raise abort_reason_error(signal)
                work = asyncio.get_running_loop().run_in_executor(None, _read_file, path)
                workers.add(work)
                work.add_done_callback(workers.discard)
                raw = await wait_with_abort(CleanupPromise(work), signal)
            except Exception as error:
                if aborted(signal):
                    raise abort_reason_error(signal)
                return failed(name, error, isinstance(error, (FileNotFoundError, NotADirectoryError)))
            try:
                value = _parse(raw, path)
            except Exception as error:
                return failed(name, error, True)
            reported.pop(name, None)
            return dict(value, kind='loaded')

        def provider(control):
            async def listing(options):
                reads = await asyncio.gather(*(read(name, options.get('signal')) for name in NAMES))
                candidates = []
                for name, value in zip(NAMES, reads):
                    if value['kind'] != 'loaded':
                        continue
                    directory = os.path.join(root, name)
                    candidates.append(dict(name=name, description=value['description'],
                        invocation=dict(modelInvocable=True, userInvocable=True), provider='dsh-office', source='bundled',
                        rank=600, resourceBase=dict(kind='directory', path=directory.replace(os.sep, '/')),
                        locator=os.path.join(directory, 'SKILL.md')))
                return dict(candidates=candidates, complete=all(value['kind']=='loaded' or value['persistent'] for value in reads))

            async def get(candidate, options):
                summary = {key: value for key, value in candidate.items() if key not in ['rank', 'locator']}
                value = await read(candidate['name'], options.get('signal'))
                if value['kind'] == 'failed':
                    if not value['persistent']:
                        raise value['error']
                    control.invalidate()
                    return None
                content = value['content']
                if candidate['name'] in NAMES[1:]:
                    content += '\n\n## Python environment\n\n' + PYTHON_ENVIRONMENTS[self.config['pythonEnvironment']]
                return dict(summary, content=content)
            return SimpleNamespace(name='dsh-office', list=listing, get=get)
        ctx.skills.registerProvider(provider)
