"""Current live locale/theme configuration and pre-plugin theme bootstrap."""
import re

from dsh.cordis.json_text import stringify_json
from dsh.cordis.plugin import Plugin
from dsh.cordis.schema import Schema as z
from dsh.cordis.text import trim_js

FONT_SPECS = {
    'text': ('fontSize', '--dsh-content-font-size', 10, 22, 14),
    'code': ('codeFontSize', '--dsh-code-font-size', 10, 16, 11),
    'terminal': ('terminalFontSize', '--dsh-terminal-font-size', 10, 20, 13),
}
GENERIC_FAMILIES = frozenset(('serif', 'sans-serif', 'monospace', 'cursive', 'fantasy',
    'system-ui', 'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded', 'emoji',
    'math', 'fangsong', '-apple-system', 'blinkmacsystemfont'))
JS_SPACES = re.compile('[\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+')
UNSAFE_FAMILY = re.compile('["\'\\\\<>\x00-\x1f\x7f]')


def normalize_font_family(value):
    names = []
    for part in value.split(','):
        name = trim_js(JS_SPACES.sub(' ', UNSAFE_FAMILY.sub('', part)))
        if name:
            names.append(name if name.lower() in GENERIC_FAMILIES else '"' + name + '"')
    return ', '.join(names)


def boot_theme_injections(preference='system', sizes=None, families=None):
    sizes = sizes or {role: spec[4] for role, spec in FONT_SPECS.items()}
    families = families or {role: '' for role in FONT_SPECS}
    light = ':root{color-scheme:light}body{background-color:#fff;--dsh-boot-bg:#fff}'
    dark = ':root{color-scheme:dark}body{background-color:#151517;--dsh-boot-bg:#151517}'
    style = light if preference == 'light' else dark if preference == 'dark' else light + '@media(prefers-color-scheme:dark){' + dark + '}'
    setters = ''.join('\n  document.body.style.setProperty(' + stringify_json(spec[1]) + ', ' + stringify_json(str(int(sizes[role])) + 'px') + ')'
                      for role, spec in FONT_SPECS.items())
    for role in FONT_SPECS:
        family = normalize_font_family(families[role])
        if family:
            setters += '\n  document.body.style.setProperty(' + stringify_json('--dsh-font-family-' + role) + ', ' + stringify_json(family) + ')'
    script = '''(() => {
  const preference = %s
  const systemDark = preference === 'system'
    && typeof matchMedia !== 'undefined'
    && matchMedia('(prefers-color-scheme: dark)').matches
  const dark = preference === 'dark' || systemDark
  document.documentElement.dataset.dsThemeSource = preference
  document.body.toggleAttribute('data-ds-dark-theme', dark)%s
})()''' % (stringify_json(preference), setters)
    return [dict(kind='style', text=style), dict(kind='script', placement='body', text=script)]


def configure_settings(ctx):
    def settings(child):
        child.effect(lambda: child.settings.configure(dict(auto=False), ctx.fiber))
    ctx.inject(['settings'], settings)


class CurrentThemeHost(Plugin):
    Config = z.object(dict(
        preference=z.union(['light', 'dark', 'system']).default('system').volatile(),
        **{spec[0]: z.number().step(1).min(spec[2]).max(spec[3]).default(spec[4]).volatile() for spec in FONT_SPECS.values()},
        **{role + 'FontFamily': z.string().default('').volatile() for role in ('text', 'code', 'terminal')}))

    def apply(self, ctx):
        configure_settings(ctx)
        def inject(table, *_peer):
            table.extend(boot_theme_injections(self.config['preference'].get(),
                {role: self.config[spec[0]].get() for role, spec in FONT_SPECS.items()},
                {role: self.config[role + 'FontFamily'].get() for role in FONT_SPECS}))
        ctx.on('webserver/index-inject', inject, prepend=True)


class CurrentLocaleHost(Plugin):
    Config = z.object(dict(preference=z.string().pattern(re.compile(r'^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$')).required(False).volatile()))

    def apply(self, ctx):
        configure_settings(ctx)


class CurrentGeneralSettingsHost(Plugin):
    Config = z.object(dict(welcomeNoticeVersion=z.string().volatile()))

    def apply(self, ctx):
        configure_settings(ctx)
