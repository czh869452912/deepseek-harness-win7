"""Reversible early injection; reject a final HTML document that moved it late."""
from html.parser import HTMLParser
from pathlib import Path

from dsh.cordis.plugin import Plugin


SCRIPT = Path(__file__).with_name('compat.js').read_text(encoding='utf-8')


class _IndexScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts = []
        self.current = None
        self.csp = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script':
            self.current = [values, '']
        if tag == 'meta' and values.get('http-equiv', '').lower() == 'content-security-policy':
            self.csp.append(values.get('content', ''))

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


class BrowserCompatibilityPlugin(Plugin):
    id = 'browser-compatibility'
    name = '@deepseek-win7/dsh-host-browser-compatibility'
    inject = ['webServer']

    def apply(self, ctx):
        def inject(rows):
            rows.insert(0, dict(kind='script', placement='head', text=SCRIPT))
        ctx.on('webserver/index-inject', inject)
        ctx.set_service('browserCompatibility', self)

    def validate_index(self, html):
        parser = _IndexScripts()
        parser.feed(html)
        executable = [row for row in parser.scripts if row[0].get('type', '').lower() in
                      ('', 'module', 'text/javascript', 'application/javascript')]
        if not executable or executable[0] != [{}, SCRIPT]:
            raise RuntimeError('browser compatibility must execute before all application scripts')
        if sum(text == SCRIPT for _, text in executable) != 1:
            raise RuntimeError('browser compatibility must be injected exactly once')
        for policy in parser.csp:
            directives = dict((pieces[0], pieces[1:]) for pieces in
                              (part.strip().split() for part in policy.split(';')) if pieces)
            sources = directives.get('script-src-elem', directives.get('script-src', directives.get('default-src')))
            if sources is not None and ("'unsafe-inline'" not in sources or
                    any(value.startswith(("'nonce-", "'sha256-", "'sha384-", "'sha512-")) for value in sources)):
                raise RuntimeError('index CSP blocks the inline browser compatibility adapter')
        return html
