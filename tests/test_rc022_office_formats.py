import pytest

from dsh.office.formats import check_render_arguments,check_conversion_arguments,check_parameter_names,input_family
from dsh.office.content import render_images_content


def test_argument_refusal_uses_office_operation_authority_and_ecmascript_whitespace():
    assert input_family('render','C:\\input\\report.XLSX')=='spreadsheet'
    with pytest.raises(ValueError,match='pages does not apply'):check_render_arguments(dict(pages=[1]),'spreadsheet')
    with pytest.raises(ValueError,match='worksheet name'):check_conversion_arguments(dict(input='file.xlsx',format='csv',sheet='\ufeff'),'spreadsheet')
    with pytest.raises(ValueError,match='pages must list'):check_render_arguments(dict(pages=[True]),'text')
    with pytest.raises(ValueError,match='applies only to office_render'):check_parameter_names('office_convert',dict(pages=[1]))


def test_model_content_preserves_attachment_encoding_and_copies_original_dimensions():
    image=dict(attachmentId='stored',mediaType='image/webp',bytes=3,width=10,height=20,originalDimensions=dict(width=100,height=200),sheet='Sheet',range='A1:B2')
    value=dict(path='C:\\report.xlsx',pageCount=1,dpi=96,images=[image],missingFonts=['Font']);blocks=render_images_content(value)
    assert blocks[1]['text']=='Sheet "Sheet" A1:B2: 10x20 px'
    attachment=blocks[2]['attachment'];assert attachment['mediaType']=='image/webp' and 'sheet' not in attachment
    attachment['originalDimensions']['width']=0;assert image['originalDimensions']['width']==100
