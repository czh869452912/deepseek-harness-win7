"""
1:1 Test Parity Suite for @deepseek-ai/dsh-scope
Covers:
- Scope tagging, nearest-tag inheritance
- Scope hierarchy, parent binding, cycle detection
- Scoped routing carriers and scopeTarget filtering
- NamedEntries and AnonymousEntries with undo disposers
- ScopedLayers inheritance chains
"""

import pytest
from dsh.cordis.context import Context
from dsh.core.scope import (
    AnonymousEntries,
    NamedEntries,
    ScopedLayers,
    bind_scope_parent,
    carrier_key_of,
    create_scope,
    is_scope_carrier,
    scope_chain_of,
    scope_of,
    scope_parent_of,
    scope_target,
)


class Key:
    def __init__(self, name: str):
        self.name = name


def test_create_scope_tags_contexts_and_nearest_wins():
    ctx = Context()
    outer_key = Key("outer")
    inner_key = Key("inner")

    outer = create_scope(ctx, outer_key)
    inner = create_scope(outer.ctx, inner_key)

    assert scope_of(ctx) is None
    assert scope_of(outer.ctx) == outer_key
    assert scope_of(outer.ctx.extend({})) == outer_key
    assert scope_of(inner.ctx) == inner_key


def test_scope_parent_binding_and_cycle_rejection():
    root = Key("root")
    child = Key("child")
    grandchild = Key("grandchild")

    binding1 = bind_scope_parent(child, root)
    assert scope_parent_of(child) == root
    assert scope_chain_of(child) == [child, root]

    binding2 = bind_scope_parent(grandchild, child)
    assert scope_chain_of(grandchild) == [grandchild, child, root]

    # Re-binding already bound key directly throws
    with pytest.raises(ValueError, match="already bound"):
        bind_scope_parent(child, grandchild)

    # Rebinding through binding handle forming cycle throws
    with pytest.raises(ValueError, match="cycle"):
        binding1.rebind(grandchild)


def test_scope_target_and_carrier_filtering():
    base = object()
    key_a = Key("A")
    key_b = Key("B")

    carrier_a = scope_target(base, key_a)
    assert is_scope_carrier(carrier_a) is True
    assert carrier_key_of(carrier_a) == key_a

    ctx = Context()
    scope_a = create_scope(ctx, key_a)
    scope_b = create_scope(ctx, key_b)

    # Untagged context passes
    assert carrier_a(ctx) is True

    # Matching scope passes
    assert carrier_a(scope_a.ctx) is True

    # Different scope fails
    assert carrier_a(scope_b.ctx) is False


def test_named_and_anonymous_entries():
    # NamedEntries
    named = NamedEntries(lambda name: ValueError(f"duplicate {name}"))
    undo1 = named.insert("a", 1)
    assert named.get("a") == 1
    assert named.has("a") is True
    assert list(named.keys()) == ["a"]

    with pytest.raises(ValueError, match="duplicate a"):
        named.insert("a", 2)

    undo1()
    assert named.has("a") is False
    assert named.is_empty() is True

    # AnonymousEntries
    anon = AnonymousEntries()
    u1 = anon.insert("x")
    u2 = anon.insert("y")
    assert list(anon.values()) == ["x", "y"]
    assert anon.is_empty() is False

    u1()
    assert list(anon.values()) == ["y"]
    u2()
    assert anon.is_empty() is True


def test_scoped_layers():
    layers = ScopedLayers(lambda k: {"key": k, "items": []})
    ctx = Context()
    root_k = Key("root")
    child_k = Key("child")
    bind_scope_parent(child_k, root_k)

    child_scope = create_scope(ctx, child_k)

    layer_child = layers.layer_of(child_scope.ctx)
    layer_child["items"].append("child_item")

    layer_root = layers.layer_of(root_k)
    layer_root["items"].append("root_item")

    chain = layers.chain_layers_of(child_scope.ctx)
    assert len(chain) == 3  # child, root, unscoped
    assert chain[0]["items"] == ["child_item"]
    assert chain[1]["items"] == ["root_item"]
