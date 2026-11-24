import {readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';

// Pass the installed regexpu-core 6.4.0 package directory.
const require = createRequire(import.meta.url);
const compiler = resolve(process.argv[2]);
if (require(compiler + '/package.json').version !== '6.4.0') throw Error('Expected regexpu-core 6.4.0');
const rewrite = require(compiler);
const input = 'packages/client/ui-sidebar-documentpreview/lib/client.pdf.js';
const source = readFileSync(input, 'utf8').replaceAll('\r\n', '\n');
const match = source.match(/findLinks\(text\)\{this\.#regex\?\?=(\/[^\n]+?\/gv)(?=[;,])/);
if (!match) throw Error('Expected pinned PDF.js auto-link regex');
const original = match[1];
const replacement = '/' + rewrite(original.slice(1, -3), 'gv', {unicodeSetsFlag:'transform'}) + '/gu';
new RegExp(replacement.slice(1, -3), 'gu');
writeFileSync('dsh/host/browser_compat/pdf-regexp.json', JSON.stringify({
  sourceSha256:createHash('sha256').update(source).digest('hex'),
  original, replacement
}, null, 2) + '\n', 'utf8');
