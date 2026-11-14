"""Exact profile inputs feeding the HMR-owned generation transaction."""
import json
import os

from dsh.boot.runtime_resolution import _field


async def watch_profile(hmr, profile):
    from dsh.boot.profile import PROFILE_PATCH_FILENAME, read_profile_manifest
    patch_files = [_field(profile, 'patchPath'), os.path.join(_field(profile, 'home'), PROFILE_PATCH_FILENAME)]
    manifest = os.path.join(_field(profile, 'dir'), 'package.json')
    last_inputs = None
    last_bundles = json.dumps(_field(profile, 'startedBundles'), ensure_ascii=False, separators=(',', ':'))

    async def refresh(manifest_only):
        nonlocal last_inputs, last_bundles
        value = read_profile_manifest('dsh', _field(profile, 'dir'))
        bundles = json.dumps(value.get('dsh', {}).get('profile', {}).get('bundles', []), ensure_ascii=False, separators=(',', ':'))
        if manifest_only and bundles == last_bundles:
            return
        content = []
        for filename in patch_files:
            try:
                with open(filename, 'r', encoding='utf-8', newline='') as stream:
                    content.append(stream.read())
            except FileNotFoundError:
                content.append(None)
        inputs = json.dumps([bundles, *content], ensure_ascii=False, separators=(',', ':'))
        if inputs == last_inputs:
            return
        result = await hmr.reconcileProfile()
        if 'restartReason' in result:
            hmr.ctx.logger.warn('restart required: %s', result['restartReason'])
        if result['pending']:
            hmr.ctx.logger.warn('changed modules keep running their previous code until a restart: %s', result['pending'])
        last_inputs, last_bundles = inputs, bundles
        for diagnostic in result['warnings']:
            hmr.ctx.logger.warn(diagnostic)

    for filename in patch_files:
        await hmr.watchConfig(filename, lambda: refresh(False))
    await hmr.watchConfig(manifest, lambda: refresh(True))
