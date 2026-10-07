import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.tool_fs import ToolFsPlugin
from dsh.attachment.local import LocalAttachmentStore
from dsh.llm.llm_service import LlmRuntime
try:
    from dsh.fs.tool_read_image import image_media_type_for_path, format_image_read_output, image_ref_from_value
except ImportError:
    image_media_type_for_path = None


async def main():
    work = Path(os.environ['DSH_FS_FIXTURE_WORK'])
    fixture = work / 'read-image-fixture-v2'
    rows = []
    for path in ['red.png','RED.JPG','red.jpeg','red.webp','red.gif','red.txt','.png','red.png/leaf']:
        rows.append(dict(name='extension:' + path, value=image_media_type_for_path(path) if image_media_type_for_path else dict(missingExport=True)))
    image = dict(attachmentId='sha256:' + 'a' * 64, mediaType='image/png', bytes=69, width=8, height=8, name='red.png')
    for name, dimensions in [('plain', None), ('same', dict(width=16, height=16)), ('axes', dict(width=16, height=24)), ('tie', dict(width=5, height=5))]:
        value = dict(image)
        if dimensions is not None:
            value['originalDimensions'] = dimensions
        rows.append(dict(name='render:' + name, value=dict(text=format_image_read_output('red.png', value), reference=image_ref_from_value(value)) if image_media_type_for_path else dict(missingExport=True)))
    names = ['positive','fallback','latest-header','text-model','unknown-modalities','missing-llm','missing-provider','missing-model','missing-agent','bad-extension','blank-path','missing-file','directory','type-mismatch','pixel-limit','dimension-limit','byte-cap','disallowed-type','attachment-gate','unmount-store','remount-store','cancel-before']
    for name in names:
        directory = fixture / name
        ctx = Context()
        lookups, observed = [], []
        record = dict(name=name, lookups=lookups, observed=observed)

        class Adapter:
            async def resolve_model(self, provider, model, signal=None):
                lookups.append(dict(provider=provider, model=model))
                info = dict(provider=provider, id=model, name=model)
                if model != 'unknown':
                    info['inputModalities'] = ['text'] if model == 'text' else ['text', 'image']
                return info

            def stream(self, options):
                raise RuntimeError('image observer must not stream')

        try:
            await ctx.plugin(SystemPrompt)
            await ctx.plugin(ToolsPlugin)
            await ctx.plugin(FsLocalPlugin, dict(cwd=str(directory)))
            if name != 'missing-llm':
                await ctx.plugin(LlmRuntime)
                ctx.get('llm').register_adapter(['image-fixture'], Adapter())
            configuration = dict(dshHome=str(directory / 'python-home'))
            if name == 'pixel-limit':
                configuration['maxImagePixels'] = 4
            if name == 'dimension-limit':
                configuration['maxImageDimension'] = 2
            if name == 'byte-cap':
                configuration['maxImageBytes'] = 32
            store = None
            if name != 'attachment-gate':
                store = await ctx.plugin(LocalAttachmentStore, configuration)
            await ctx.plugin(ToolFsPlugin)
            if name in ('unmount-store', 'remount-store'):
                await store.dispose()
                if name == 'remount-store':
                    store = await ctx.plugin(LocalAttachmentStore, configuration)
            if name == 'disallowed-type':
                ctx.get('attachments')._image_limits = dict(ctx.get('attachments').image_limits, mediaTypes=['image/jpeg'])
            ctx.on('fs/observed', lambda target, observation, execution: observed.append(dict(path=target.displayPath, **observation)))
            model = 'text' if name == 'text-model' else 'unknown' if name == 'unknown-modalities' else 'vision'
            config = dict(model=model)
            if name != 'missing-provider':
                config['provider'] = 'image-fixture'
            if name == 'missing-model':
                del config['model']
            header = None if name == 'fallback' else dict(config=config)
            options = dict(provider='image-fixture', model=model) if name == 'fallback' else dict(provider='image-fixture', model='text') if name == 'latest-header' else {}
            agent = SimpleNamespace(options=options, session=SimpleNamespace(header=dict(cwd=str(directory)), requestHeader=lambda: header, deriveMessages=lambda: [], append=lambda *unused: None))
            signal = AbortController()
            if name == 'cancel-before':
                signal.abort()
            file_path = 'red.txt' if name == 'bad-extension' else '  ' if name == 'blank-path' else 'missing.png' if name == 'missing-file' else 'folder.png' if name == 'directory' else 'red.jpg' if name == 'type-mismatch' else 'red.png'
            result = await ctx.get('tools').execute(ToolExecutionInput(signal=signal.signal, call_id='image-call', name='read_image', arguments=dict(file_path=file_path), agent=None if name == 'missing-agent' else agent))
            value = dict(isError=result.isError, content=copy.deepcopy(result.content))
            if result.value is not None:
                value['value'] = copy.deepcopy(result.value)
            if result.error is not None:
                value['error'] = copy.deepcopy(result.error)
            if result.meta is not None:
                value['meta'] = copy.deepcopy(result.meta)
            if result.additional_contexts:
                value['additionalContexts'] = copy.deepcopy(result.additional_contexts)
            record['result'] = value
            record['allSchemas'] = ctx.get('tools').schemas()
            record['schema'] = next((item for item in ctx.get('tools').schemas() if item['name'] == 'read_image'), None)
            content = next((block for block in result.content if block['type'] == 'image'), None)
            if content is not None:
                stored = ctx.get('attachments').read_image(content['attachment'])
                record['stored'] = dict(dataHex=stored['data'].hex(), ref=stored['ref'])
        except Exception as error:
            record['error'] = dict(name=getattr(error, 'name', type(error).__name__), message=str(error))
        finally:
            await ctx.fiber.dispose()
        rows.append(record)
    with arguments.output.open('x', encoding='utf-8') as stream:
        modules = {}
        for name, module in sorted(sys.modules.items()):
            selected = getattr(module, '__file__', None)
            if selected and (name == 'dsh' or name.startswith('dsh.')):
                path = Path(selected).resolve()
                relative = path.relative_to(root).as_posix()
                modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        json.dump(dict(root=str(root), python=sys.version, executable=sys.executable, modules=modules, rows=rows), stream, indent=2, ensure_ascii=False)
        stream.write('\n')


asyncio.run(main())
