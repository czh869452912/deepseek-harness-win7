"""Actual original/public SDK and browser owner: Calc, Impress and Writer matrix."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh.office.browser_engine import BrowserOfficeEngine


def make_fixtures(directory):
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/><sheet name="Other" sheetId="2" r:id="rId2"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>',
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><v>2</v></c></row><row r="2"><c r="A2"><v>3</v></c></row><row r="3"><c r="A3"><f>SUM(A1:A2)</f><v>999</v></c></row></sheetData></worksheet>',
        'xl/worksheets/sheet2.xml': '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>Data!A3*2</f><v>0</v></c></row></sheetData></worksheet>',
    }
    workbook = directory / 'formula.xlsx'
    with zipfile.ZipFile(str(workbook), 'w', zipfile.ZIP_DEFLATED) as zipped:
        for name, content in files.items():
            zipped.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), content.encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED)
    slides = directory / 'slides.odp'
    ns = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
          'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
          'xmlns:presentation="urn:oasis:names:tc:opendocument:xmlns:presentation:1.0"')
    content = '<office:document-content ' + ns + ' office:version="1.3"><office:body><office:presentation>'
    for number in (1, 2):
        content += ('<draw:page draw:name="Slide {0}" draw:master-page-name="Default"><draw:frame '
                    'svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="5cm">'
                    '<draw:text-box><text:p>Office slide {0}</text:p></draw:text-box></draw:frame></draw:page>').format(number)
    content += '</office:presentation></office:body></office:document-content>'
    styles = ('<office:document-styles ' + ns + ' office:version="1.3"><office:automatic-styles>'
              '<style:page-layout style:name="PM1"><style:page-layout-properties svg:width="28cm" svg:height="21cm"/>'
              '</style:page-layout></office:automatic-styles><office:master-styles>'
              '<style:master-page style:name="Default" style:page-layout-name="PM1"/>'
              '</office:master-styles></office:document-styles>')
    manifest = ('<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.3">'
                '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/>'
                '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
                '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    with zipfile.ZipFile(str(slides), 'w') as zipped:
        for name, value in [('mimetype', 'application/vnd.oasis.opendocument.presentation'),
                            ('content.xml', content), ('styles.xml', styles), ('META-INF/manifest.xml', manifest)]:
            zipped.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), value.encode('utf-8'))
    return workbook, slides


def digest(path):
    data = Path(path).read_bytes()
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def package_content(path):
    # Exclude only the original engine's two wall-clock XML properties.
    dates = {'{http://purl.org/dc/terms/}created', '{http://purl.org/dc/terms/}modified',
             '{urn:oasis:names:tc:opendocument:xmlns:meta:1.0}creation-date', '{http://purl.org/dc/elements/1.1/}date'}
    field_ids = {}
    def tree(node):
        attributes = dict(node.attrib)
        if node.tag == '{http://schemas.openxmlformats.org/drawingml/2006/main}fld' and attributes.get('type') == 'slidenum':
            identity = attributes.get('id', '')
            identifier = uuid.UUID(identity)
            assert identifier.version == 4 and identifier.variant == uuid.RFC_4122
            attributes['id'] = field_ids.setdefault(identity, 'generated-field-' + str(len(field_ids)))
        children = [child for child in node if child.tag not in dates]
        if node.tag == '{urn:oasis:names:tc:opendocument:xmlns:office:1.0}master-styles':
            name = '{urn:oasis:names:tc:opendocument:xmlns:style:1.0}name'
            names = [child.get(name) for child in children]
            # Named master declarations are referenced by name. Preserve every
            # definition and attribute, comparing this collection as a mapping.
            if all(names) and len(set(names)) == len(names):
                children = sorted(children, key=lambda child: (child.tag, child.get(name)))
        return [node.tag, sorted(attributes.items()), node.text, node.tail,
                [tree(child) for child in children]]
    with zipfile.ZipFile(str(path)) as zipped:
        return {name: tree(ET.fromstring(zipped.read(name))) if name.endswith(('.xml', '.rels'))
                else hashlib.sha256(zipped.read(name)).hexdigest() for name in sorted(zipped.namelist()) if not name.endswith('/')}


async def main():
    parser = argparse.ArgumentParser()
    for key in ('source', 'node', 'browser', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.output.absolute()
    assert (root / '.goose/out').absolute() in out.parents
    out.mkdir()
    temporary = out / 'tmp'
    temporary.mkdir()
    workbook, slides = make_fixtures(out)
    operations = []
    def add(name, kind, input_path, suffix=None, **values):
        request = dict(inputPath=str(input_path), **values)
        request['outputDir' if kind == 'renderImages' else 'outputPath'] = str(out / ('source-' + name + ('.' + suffix if suffix else '')))
        operations.append(dict(name=name, kind=kind, request=request))
    add('calc-recalculate', 'recalculate', workbook, 'xlsx')
    add('calc-csv', 'convert', out / 'source-calc-recalculate.xlsx', 'csv', sheet='Data')
    add('calc-ods', 'convert', workbook, 'ods')
    add('ods-recalculate', 'recalculate', out / 'source-calc-ods.ods', 'xlsx')
    add('calc-pdf', 'render', workbook, 'pdf')
    add('calc-range', 'renderImages', workbook, sheet='Data', range='A1:A3', dpi=72)
    add('calc-images', 'renderImages', workbook, dpi=72)
    add('calc-missing-sheet', 'convert', workbook, 'csv', sheet='Missing')
    add('impress-pptx', 'convert', slides, 'pptx')
    add('impress-odp', 'convert', slides, 'odp')
    add('impress-pdf', 'render', slides, 'pdf')
    add('impress-page-two', 'renderImages', slides, pages=[2], dpi=72)
    add('pptx-pdf', 'render', out / 'source-impress-pptx.pptx', 'pdf')
    options = dict(fontDirectories=[str(Path(os.environ['WINDIR']) / 'Fonts' / name)
                                   for name in ('arial.ttf', 'arialbd.ttf', 'cour.ttf', 'times.ttf')],
                   fontMetadataCacheDirectory=False)
    request_path = out / 'source-request.json'
    request_path.write_text(json.dumps(dict(options=options, operations=operations, report=str(out / 'source-report.json'))), encoding='utf-8')
    command = [str(args.node.absolute()), str(root / 'scripts/oracles/rc022_office_converter.mjs'),
               str(args.source.absolute()), str(request_path)]
    with (out / 'source.log').open('wb') as log:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    assert completed.returncode == 0
    expected = json.loads((out / 'source-report.json').read_text(encoding='utf-8'))['rows']
    for row in expected:
        assert row['ok'] is (row['name'] != 'calc-missing-sheet'), row
    package = args.source.absolute() / 'node_modules/.pnpm/@deepseek-ai+libreoffice-kit-wasm@0.2.3/node_modules/@deepseek-ai/libreoffice-kit-wasm'
    engine = BrowserOfficeEngine(str(args.browser.absolute()), str(package), temporary_directory=str(temporary))
    rows = []
    report = dict(command=[sys.executable] + sys.argv, rows=rows,
                  fixtures={p.name: digest(p) for p in (workbook, slides)},
                  comparison_policy=dict(csv_and_png='Exact bytes and public results.',
                    packages='All member content; XML timestamp properties omitted, uniquely named ODF master declarations compared as a mapping, valid RFC4122 v4 slide-number field IDs compared by consistent identity renaming.',
                    pdf='Original public metadata/page count and original SDK output validation; raw output digests retained, no PDF byte identity claim.',
                    errors='Host language error classes differ; original category and exact message must match.'))
    try:
        converter = await engine.createConverter(options)
        for operation, original in zip(operations, expected):
            values = dict(operation['request'])
            key = 'outputDir' if operation['kind'] == 'renderImages' else 'outputPath'
            values[key] = values[key].replace('source-', 'browser-')
            try:
                value = await getattr(converter, operation['kind'])(values)
                native = dict(ok=True, result=value)
            except Exception as cause:
                native = dict(ok=False, message=str(cause), code=getattr(cause, 'code', None))
            row = dict(name=operation['name'], source=original, browser=native)
            if original['ok'] and native['ok']:
                a, b = dict(native['result']), dict(original['result'])
                if key == 'outputDir':
                    for result in (a, b):
                        result['images'] = [dict(item, path=Path(item['path']).name, pixels=digest(item['path'])) for item in result['images']]
                equal = a == b
                if key == 'outputPath':
                    path = Path(values[key])
                    row.update(browser_output=digest(path), source_output=digest(operation['request'][key]))
                    if path.suffix == '.csv':
                        equal = equal and row['browser_output'] == row['source_output']
                    elif path.suffix in ('.xlsx', '.ods', '.pptx', '.odp'):
                        left, right = package_content(path), package_content(operation['request'][key])
                        row['package_parts_equal'] = left == right
                        equal = equal and row['package_parts_equal']
            else:
                equal = (not original['ok'] and not native['ok'] and
                         (original.get('code'), original['message']) == (native.get('code'), native.get('message')))
            row['equal'] = equal
            rows.append(row)
            print(json.dumps(dict(name=row['name'], equal=equal, original_ok=original['ok'])), flush=True)
            assert equal, row
        namespace = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        for prefix in ('source', 'browser'):
            with zipfile.ZipFile(str(out / (prefix + '-calc-recalculate.xlsx'))) as zipped:
                first = ET.fromstring(zipped.read('xl/worksheets/sheet1.xml'))
                second = ET.fromstring(zipped.read('xl/worksheets/sheet2.xml'))
                assert first.find('.//s:c[@r="A3"]/s:v', namespace).text == '5'
                assert second.find('.//s:c[@r="A1"]/s:v', namespace).text == '10'
        report['status'] = 'passed'
    except BaseException as cause:
        report.update(status='failed', error=repr(cause))
        raise
    finally:
        await engine.close()
        report.update(activeTasks=len(engine.carrier.active), remainingProfiles=[p.name for p in temporary.iterdir()])
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
