"""Expose host roots to the original SDK's Office discovery and font scanner."""
import os
import posixpath
import sys

from .font_volume import FontVolume


def system_font_directories(platform=None, home=None, env=None):
    platform = sys.platform if platform is None else platform
    home = os.path.expanduser('~') if home is None else home
    env = os.environ if env is None else env
    if platform == 'win32':
        import ntpath
        return [ntpath.normpath(ntpath.join(env.get('SystemRoot', 'C:\\Windows'), 'Fonts')),
                ntpath.normpath(ntpath.join(env.get('LOCALAPPDATA', ntpath.join(home, 'AppData', 'Local')), 'Microsoft', 'Windows', 'Fonts'))]
    if platform == 'darwin':
        assets = '/System/Library/AssetsV2'
        import re
        try:
            mobile = [posixpath.join(assets, name) for name in sorted(os.listdir(assets)) if re.fullmatch(r'com_apple_MobileAsset_Font[0-9]*', name)]
        except (FileNotFoundError, PermissionError, NotADirectoryError):
            mobile = []
        return ['/System/Library/Fonts', '/Library/Fonts', posixpath.normpath(posixpath.join(home, 'Library/Fonts'))] + mobile
    shared = [entry for entry in env.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share').split(':') if entry]
    return list(dict.fromkeys(posixpath.normpath(path) for path in [posixpath.join(entry, 'fonts') for entry in shared] +
                             [posixpath.join(home, '.fonts'), posixpath.join(env.get('XDG_DATA_HOME', posixpath.join(home, '.local/share')), 'fonts')]))


def host_font_volume(options, check=None, *, home=None, env=None):
    """Index primary roots, exposing optional Office trees for original JS policy.

    No Office family/name filtering or locale sorting is reproduced in Python.
    Supplemental enumeration has no file-count gate: the SDK applies its own
    remaining budget *after* discovery, basename ordering and deduplication.
    """
    home = os.path.expanduser('~') if home is None else home
    env = os.environ if env is None else env
    primary = FontVolume(options.get('fontDirectories', system_font_directories(home=home, env=env)),
                         max_files=options.get('maxFontFiles', 20000),
                         max_file_bytes=options.get('maxFontFileBytes', 268435456), check=check)
    host = dict(platform=sys.platform, home=home, env={})
    if 'fontDirectories' in options:
        return primary, host
    roots = []
    if sys.platform == 'win32':
        host['home'] = os.path.realpath(os.path.abspath(home))
        for key in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            if key in env:
                host['env'][key] = os.path.realpath(os.path.abspath(env[key]))
        for key in ('ProgramFiles', 'ProgramFiles(x86)'):
            if host['env'].get(key):
                roots.append(os.path.join(host['env'][key], 'Microsoft Office', 'root', 'vfs', 'Fonts', 'private'))
        roots.append(os.path.join(host['env'].get('LOCALAPPDATA', os.path.join(host['home'], 'AppData', 'Local')), 'Microsoft', 'FontCache'))
    elif sys.platform == 'darwin':
        for base in ('/Applications', os.path.join(home, 'Applications')):
            for app in ('Word', 'Excel', 'PowerPoint'):
                roots.append(os.path.join(base, 'Microsoft ' + app + '.app/Contents/Resources/DFonts'))
        roots.append(os.path.join(home, 'Library/Group Containers/UBF8T346G9.Office/FontCache'))
    supplemental = FontVolume(roots, max_files=9007199254740991,
                              max_file_bytes=options.get('maxFontFileBytes', 268435456),
                              check=check, include_directories=True)
    for name in ('assets', 'files', 'sources', 'directories'):
        getattr(primary, name).update(getattr(supplemental, name))
    return primary, host
