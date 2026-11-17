import zipfile

from scripts.rc022_office_format_probe import package_content


def package(tmp_path, name, xml):
    path = tmp_path / name
    with zipfile.ZipFile(str(path), 'w') as zipped:
        zipped.writestr('content.xml', xml.encode('utf-8'))
    return package_content(path)


def test_named_master_definitions_preserve_content_and_references(tmp_path):
    head = ('<o:master-styles xmlns:o="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:s="urn:oasis:names:tc:opendocument:xmlns:style:1.0">')
    first = '<s:master-page s:name="Data" s:page-layout-name="M1"/>'
    second = '<s:master-page s:name="Other" s:page-layout-name="M2"/>'
    left = package(tmp_path, 'left.ods', head + first + second + '</o:master-styles>')
    assert left == package(tmp_path, 'reordered.ods', head + second + first + '</o:master-styles>')
    assert left != package(tmp_path, 'changed.ods', head + first + second.replace('M2', 'M1') + '</o:master-styles>')


def test_generated_field_identities_preserve_repeated_identity_and_content(tmp_path):
    ids = ['{00000000-0000-4000-8000-000000000001}', '{00000000-0000-4000-8000-000000000002}']
    def xml(a, b, text='number'):
        return ('<root xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:fld type="slidenum" id="' + a + '"><a:t>' + text + '</a:t></a:fld>'
                '<a:fld type="slidenum" id="' + b + '"/></root>')
    original = package(tmp_path, 'left.pptx', xml(ids[0], ids[1]))
    assert original == package(tmp_path, 'renamed.pptx', xml(ids[1], ids[0]))
    assert original != package(tmp_path, 'collision.pptx', xml(ids[1], ids[1]))
    assert original != package(tmp_path, 'text.pptx', xml(ids[0], ids[1], 'changed'))


def test_slide_order_and_formula_results_remain_strict(tmp_path):
    assert package(tmp_path, 'left.pptx', '<slides><slide n="1"/><slide n="2"/></slides>') != package(
        tmp_path, 'right.pptx', '<slides><slide n="2"/><slide n="1"/></slides>')
    assert package(tmp_path, 'left.xlsx', '<sheet><formula>SUM(A1:A2)</formula><value>5</value></sheet>') != package(
        tmp_path, 'right.xlsx', '<sheet><formula>SUM(A1:A2)</formula><value>999</value></sheet>')
