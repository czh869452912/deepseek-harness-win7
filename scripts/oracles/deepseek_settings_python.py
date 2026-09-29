import tempfile
from pathlib import Path

from dsh.cordis.context import Context
from dsh.llm.llm_service import LlmRuntime
from dsh.llm.llm_deepseek import LLMDeepSeekPlugin
from dsh.settings.settings_file import SettingsFilePlugin


async def observe_settings(fixture):
    with tempfile.TemporaryDirectory(prefix='dsh-paired-settings-') as directory:
        ctx = Context()
        try:
            await ctx.plugin(LlmRuntime)
            settings_fiber = await ctx.plugin(SettingsFilePlugin, dict(path=str(Path(directory) / 'settings.yaml'), watch=False))
            await ctx.plugin(LLMDeepSeekPlugin, fixture['config'])
            llm, settings = ctx.get('llm'), ctx.get('settings')
            async def snapshot():
                return dict(models=await llm.list_models('deepseek-official'), retry=llm.retry_policy('deepseek-official'), providers=llm.list_providers())
            observations = [dict(snapshot=await snapshot())]
            for update in fixture['updates']:
                accepted = True
                try:
                    await settings.update('llm-deepseek', update)
                except Exception:
                    accepted = False
                observations.append(dict(accepted=accepted, snapshot=await snapshot()))
            await settings_fiber.dispose()
            observations.append(dict(detached=True, snapshot=await snapshot()))
            return observations
        finally:
            await ctx.fiber.dispose()
