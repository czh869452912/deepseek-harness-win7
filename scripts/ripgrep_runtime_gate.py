"""Finite isolated native-search qualification on current Windows."""
import hashlib
import json
from pathlib import Path

from scripts.build_portable import RIPGREP_FILES
from scripts.llm_config_oracle import GROUP_MODULES
from scripts.import_paths import resolve_import_path


# Reviewed cold closure: the shared Core/Session graph, without catalog model
# validation, plus the actual prompt, subprocess and search providers.
REQUIRED_MODULES = (set(GROUP_MODULES['query']) - {'dsh/llm/model_info.py'}) | {
    'dsh/core/system_prompt/__init__.py', 'dsh/core/system_prompt/invariant.py',
    'dsh/core/system_prompt/layer.py', 'dsh/core/system_prompt/service.py', 'dsh/core/system_prompt/types.py',
    'dsh/fs/tool_fs_search/__init__.py', 'dsh/fs/tool_fs_search/glob.py',
    'dsh/fs/tool_fs_search/grep.py', 'dsh/fs/tool_fs_search/search_core.py',
    'dsh/subprocess/__init__.py', 'dsh/subprocess/collector.py', 'dsh/subprocess/local.py',
    'dsh/subprocess/service.py', 'dsh/subprocess/types.py',
}
RUNTIME_DAMAGES = ('missing', 'root', 'python', 'executable', 'binary', 'binary-sha', 'path',
    'override', 'node', 'version', 'version-exit', 'version-stderr', 'module', 'module-bytes',
    'glob', 'grep', 'meta', 'order', 'flag-type', 'public-extra')


def expected_public():
    common = dict(isError=False, error=None, metaPresent=True, concludesTurn=False, additionalContexts=[])
    return [
        dict(common, name='glob', value={'root': '.', 'paths': ['中文.txt']},
            content=[dict(type='text', text='中文.txt')],
            meta=dict(shape='paths', paths=['中文.txt'], truncated=False, total=1)),
        dict(common, name='grep', value={'matches': [dict(path='中文.txt', lineNumber=1, line='hello 中文')]},
            content=[dict(type='text', text='Found 1 match\n\n中文.txt\nLine 1: hello 中文')],
            meta=dict(shape='matches', files=[dict(path='中文.txt', matches=[dict(lineNumber=1, line='hello 中文')])],
                      truncated=False, total=1)),
    ]


def validate_runtime(report, root, executable, expected_modules, check_files=True):
    root = Path(root).resolve()
    if not isinstance(report, dict) or set(report) != {
            'root', 'executable', 'python', 'modules', 'workspace', 'binary', 'binarySha256',
            'path', 'explicitOverridePresent', 'hostNodeFound', 'version', 'public'}:
        raise ValueError('Native search complete runtime receipt missing')
    if (Path(report['root']).resolve() != root or Path(report['executable']).resolve() != Path(executable).resolve()
            or not report['python'].startswith('3.8.10 ')):
        raise ValueError('Native search selected root or Python differs')
    if Path(report['binary']).resolve() != root / 'dsh/fs/tool_fs_search/bin/rg.exe':
        raise ValueError('Native search selected binary differs')
    Path(report['workspace']).resolve().relative_to(root.parent)
    if (report['binarySha256'] != RIPGREP_FILES['rg.exe'][0] or report['path'] != ''
            or report['explicitOverridePresent'] is not False or report['hostNodeFound'] is not False):
        raise ValueError('Native search input or isolation differs')
    version = report['version']
    if (not isinstance(version, dict) or set(version) != {'exitCode', 'stdout', 'stderr'}
            or type(version['exitCode']) is not int or version['exitCode'] != 0 or version['stderr'] != ''
            or not isinstance(version['stdout'], str)
            or not version['stdout'].startswith('ripgrep 14.1.0 (rev e50df40a19)\n')
            or 'PCRE2 10.42 is available' not in version['stdout']):
        raise ValueError('Native search actual version process differs')
    if (not isinstance(expected_modules, dict) or set(expected_modules) != REQUIRED_MODULES
            or report['modules'] != expected_modules):
        raise ValueError('Native search actual import closure differs')
    missing = None if check_files else {}
    for name, expected in expected_modules.items():
        path = resolve_import_path(root, name, missing)
        if (path.relative_to(root).as_posix() != name or not isinstance(expected, str)
                or len(expected) != 64 or any(character not in '0123456789abcdef' for character in expected)):
            raise ValueError('Native search imported identity invalid')
        if check_files and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Native search imported bytes differ')
    if check_files and hashlib.sha256((root / 'dsh/fs/tool_fs_search/bin/rg.exe').read_bytes()).hexdigest() != report['binarySha256']:
        raise ValueError('Native search selected binary bytes differ')
    if json.dumps(report['public'], sort_keys=True, allow_nan=False) != json.dumps(expected_public(), sort_keys=True, allow_nan=False):
        raise ValueError('Native search complete ordered public results differ')
