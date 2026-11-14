"""Host operating-system admission for optional bundle layers."""
import os
import platform as host_platform
import sys

_NODE_PLATFORMS = ('aix', 'android', 'darwin', 'freebsd', 'haiku', 'linux', 'openbsd',
    'sunos', 'win32', 'cygwin', 'netbsd')
UNDECLARED = object()


class UnsupportedBundlePlatformError(ValueError):
    name = 'UnsupportedBundlePlatformError'
    def __init__(self, platforms, platform):
        super().__init__('Bundle supports Host platforms '+', '.join(platforms)+'; the DSH Host is running '+platform)


def assert_bundle_platform(platforms=UNDECLARED, platform=None, facts=None):
    if platforms is UNDECLARED:
        return
    if not isinstance(platforms, list) or not platforms or not all(isinstance(v, str) and v in _NODE_PLATFORMS+('wsl',) for v in platforms):
        raise ValueError('dsh.bundle.platforms must be a nonempty list of Node platform names or wsl')
    platform = sys.platform if platform is None else platform
    facts = facts or {}
    env = facts.get('env', os.environ)
    wsl = platform == 'linux' and (env.get('WSL_DISTRO_NAME') or env.get('WSL_INTEROP') or
        'microsoft' in facts.get('osRelease', host_platform.release()).lower())
    if platform not in platforms and not ('wsl' in platforms and wsl):
        raise UnsupportedBundlePlatformError(platforms, platform)


assertBundlePlatform = assert_bundle_platform
