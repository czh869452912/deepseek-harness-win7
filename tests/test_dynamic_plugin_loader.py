import os
import tempfile
from dsh.cordis.context import Context
from dsh.cordis.loader import Loader, resolve_plugin_class
from dsh.cordis.plugin import Plugin


def test_resolve_dotted_module_plugin():
    cls = resolve_plugin_class("dsh.todo.tool_todo.ToolTodoPlugin")
    assert cls is not None
    assert cls.__name__ == "ToolTodoPlugin"


def test_resolve_file_path_plugin():
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = os.path.join(tmpdir, "my_custom_plugin.py")
        with open(plugin_file, "w", encoding="utf-8") as f:
            f.write("""
from dsh.cordis.plugin import Plugin

class DynamicTestPlugin(Plugin):
    name = "dynamic-test"
    def apply(self, ctx):
        ctx.set_service("dynamic_val", 42)
""")

        spec = f"{plugin_file}:DynamicTestPlugin"
        cls = resolve_plugin_class(spec)
        assert cls is not None
        assert cls.__name__ == "DynamicTestPlugin"

        ctx = Context()
        loader = Loader(ctx)
        loader.load_from_dict([{"id": "test-dyn", "name": spec}])
        assert ctx.get("dynamic_val") == 42
