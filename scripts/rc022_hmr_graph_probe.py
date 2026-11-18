"""Pair actual evaluated import edges rather than rereading changed source."""
import importlib
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT = None


def prepare(output):
    global OUTPUT
    OUTPUT = output
    path = output/'input.json'
    path.write_text('{}', encoding='utf-8')
    return [path]


async def observe(directory):
    from dsh.cordis import Context
    from dsh.cordis.hmr_modules import PythonModules, source_imports
    directory.mkdir(parents=True)
    result = []
    for mode in ('static-dynamic', 'runtime-import'):
        package = directory/('_rc022_graph_'+mode.replace('-', '_'))
        package.mkdir()
        (package/'__init__.py').write_text('', encoding='utf-8')
        (package/'dep.py').write_text('value=1\n', encoding='utf-8')
        (package/'late.py').write_text('value=2\n', encoding='utf-8')
        text = ('import importlib\nfrom .dep import value\nfirst=value\ndef later():\n'
                + ('    return importlib.import_module(__package__+".late").value\n' if mode == 'static-dynamic'
                   else '    from .late import value\n    return value\n'))
        (package/'entry.py').write_text(text, encoding='utf-8')
        urls = {(package/(name+'.py')).as_uri():name for name in ('entry', 'dep', 'late')}
        ctx = Context()
        cache = PythonModules(ctx)
        sys.path.insert(0, str(directory))
        try:
            with source_imports(str(directory)):
                entry = importlib.import_module(package.name+'.entry')
            def edges():
                return sorted([urls[parent], urls[child]] for child, parents in cache.module_graph().items()
                              for parent in parents if child in urls and parent in urls)
            before = edges()
            value = entry.later()
            after = edges()
            # Neither new imports nor a syntax error on disk changes already
            # evaluated code's static dependency bindings.
            (package/'entry.py').write_text('raise RuntimeError("new disk code")\n', encoding='utf-8')
            result.append(dict(mode=mode, before=before, after=after, after_disk=edges(), value=value))
        finally:
            sys.path.remove(str(directory))
            for name in list(sys.modules):
                if name == package.name or name.startswith(package.name+'.'):
                    sys.modules.pop(name, None)
            cache.dispose()
            await ctx.fiber.dispose()
    return result


async def native():
    return await observe(OUTPUT/'files/native')


if __name__ == '__main__':
    probe.native = native
    source = ROOT/'reference'
    probe.main('rc022_hmr_graph.mts', 'Actual ESM static/dynamic and CommonJS runtime require edges versus Python traced imports. Evaluated bindings survive later source edits; graph values are normalized as edge sets.',
               [Path(__file__).resolve(), ROOT/'dsh/cordis/hmr_modules.py', ROOT/'dsh/boot/python_package.py', ROOT/'dsh/cordis/hmr.py',
                ROOT/'dsh/cordis/loader.py', source/'packages/boot/hmr/src/index.ts'], prepare, node_args=('--expose-internals',))
