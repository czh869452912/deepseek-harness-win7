import gc
import importlib.util
import sys
import types
import weakref

from dsh.cordis import hmr_modules as module


def test_import_syntax_is_reused_but_resolves_current_targets_and_reload_spec(tmp_path,monkeypatch):
    source=tmp_path/'entry.py';source.write_text('import owned_hmr_dependency\n',encoding='utf-8')
    entry=types.ModuleType('owned_hmr_entry');entry.__file__=str(source)
    entry.__spec__=importlib.util.spec_from_file_location(entry.__name__,str(source))
    first=types.ModuleType('owned_hmr_dependency');first.__file__=str(tmp_path/'first.py')
    second=types.ModuleType('owned_hmr_dependency');second.__file__=str(tmp_path/'second.py')
    monkeypatch.setitem(sys.modules,'owned_hmr_dependency',first)
    parse=module.ast.parse;calls=[]
    def counted(*args,**kwargs):calls.append(kwargs.get('filename'));return parse(*args,**kwargs)
    monkeypatch.setattr(module.ast,'parse',counted)
    assert module.PythonModules(None)._links(entry)==[module.module_url(first)]
    monkeypatch.setitem(sys.modules,'owned_hmr_dependency',second)
    assert module.PythonModules(None)._links(entry)==[module.module_url(second)]
    assert calls==[str(source)]
    source.write_text('import owned_other_dependency\n',encoding='utf-8')
    monkeypatch.setitem(sys.modules,'owned_other_dependency',first)
    entry.__spec__=importlib.util.spec_from_file_location(entry.__name__,str(source))
    assert module.PythonModules(None)._links(entry)==[module.module_url(first)]
    assert calls==[str(source)]*2
    reference=weakref.ref(entry);del entry;gc.collect()
    assert reference() is None
