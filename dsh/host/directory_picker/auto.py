"""Mount the directory-picker backend and browser surface as owned Loader rows."""
import shutil
import sys

from dsh.cordis.plugin import Plugin
from dsh.cordis.environment import launch_environment_of


def resolve_backend(host, platform, env, linux_chooser):
    if host != '127.0.0.1' or env.get('SSH_CONNECTION') or env.get('SSH_TTY'):
        return 'browse'
    if platform in ('win32', 'darwin'):
        return 'native'
    if platform.startswith('linux') and linux_chooser and (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')):
        return 'native'
    return 'browse'


class DirectoryPickerAutoPlugin(Plugin):
    id = 'host-directory-picker-auto'
    inject = ['webServer', 'loader']

    async def apply(self, ctx):
        environment = launch_environment_of(ctx)
        keys = ('SSH_CONNECTION', 'SSH_TTY', 'DISPLAY', 'WAYLAND_DISPLAY', 'PATH')
        env = {key: getattr(environment.get_from(key, ['process']), 'value', '') for key in keys}
        chooser = any(shutil.which(name, path=env['PATH']) for name in ('zenity', 'kdialog'))
        kind = resolve_backend(ctx.get('webServer').host, sys.platform, env, chooser)
        loader, ids = ctx.get('loader'), []
        async def close():
            for identity in reversed(ids):
                if identity in loader.store:
                    await loader.remove(identity)
        ctx.effect(lambda: close)
        for name in ('@deepseek-ai/dsh-host-directory-picker-' + kind,
                     '@deepseek-ai/dsh-client-ui-directory-picker-' + kind):
            ids.append(await loader.create({'name': name}))
