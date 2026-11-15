import pytest

from dsh.cordis.hmr_glob import matches


@pytest.mark.parametrize('pattern,visible,ignored', [
    ('@(foo|bar)', 'baz', 'foo'),
    ('+(foo|bar)', 'baz', 'foobar'),
    ('?(foo|bar)', 'foobar', 'bar'),
    ('*(foo|bar)', 'baz', 'barfoo'),
    ('!(foo|bar)', 'foo', 'baz'),
    ('+(foo|@(bar|baz))', 'other', 'foobarbaz'),
    ('{a,{b,c}}.js', 'd.js', 'c.js'),
    ('{1..4}.txt', '5.txt', '3.txt'),
    ('{01..03}.js', '02.js', '01..03.js'),
    ('[[:digit:]].txt', 'a.txt', '3.txt'),
    ('!!foo', 'bar', 'foo'),
    ('!!!foo', 'foo', 'bar'),
    ('foo', 'foo/', 'foo'),
    ('**/.*', '.', '..'),
])
def test_advanced_ignore_grammar(pattern, visible, ignored):
    assert not matches(visible, [pattern])
    assert matches(ignored, [pattern])


def test_a_negated_pattern_is_one_member_of_the_picomatch_union():
    assert not matches('temporary.tmp', ['!*.tmp', '*.py'])
    assert matches('temporary.tmp', ['!*.tmp', '*.tmp'])
    assert matches('foo/bar.py', ['**/@(bar|baz).py'])
    assert not matches('foo/.hidden/bar.py', ['**/@(bar|baz).py'])
