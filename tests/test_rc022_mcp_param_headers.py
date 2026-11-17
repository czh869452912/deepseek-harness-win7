import pytest

from dsh.mcp.param_headers_current import scan_declarations,encode_param_value
from scripts import rc022_mcp_param_headers_probe as corpus


@pytest.mark.asyncio
async def test_original_declaration_and_encoding_corpus():
    rows=await corpus.observe()
    assert len(rows)==275
    assert rows[0]==dict(scan=dict(valid=True,declarations=[dict(path=['value'],headerName='Trace',type='string')]),headers={'Mcp-Param-Trace':'ok'})
    assert rows[-6]['scan']['valid'] is False
    assert rows[-5]['scan']['declarations'][0]['headerName']=='two'
    assert rows[-4]['headers']=={'Mcp-Param-First':'hello','Mcp-Param-Length':'2'}
    assert rows[-2]['headers']=={}
    assert rows[-1]['headers']=={'Mcp-Param-Sibling':'accepted'}


@pytest.mark.parametrize('value,expected',[('', '=?base64??='),(' a ','=?base64?IGEg?='),('😀','=?base64?8J+YgA==?='),('=?base64?x?=','=?base64?PT9iYXNlNjQ/eD89?='),('ascii','ascii')])
def test_empty_unicode_whitespace_and_sentinel_values(value,expected):
    assert encode_param_value(value)==expected


def test_bad_declaration_never_publishes_partial_header_set():
    schema=dict(properties=dict(first={'type':'string','x-mcp-header':'Owned'},second={'type':'number','x-mcp-header':'owned'}))
    scan=scan_declarations(schema)
    assert scan==dict(valid=False,reason="x-mcp-header 'owned' is not case-insensitively unique (also declared as 'Owned')")
