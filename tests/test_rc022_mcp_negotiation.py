import asyncio
import pytest

from dsh.mcp.negotiation_current import classify_probe_outcome, SdkError
from dsh.mcp.current import RESOURCE_SCHEMAS
from dsh.mcp.schemas import parse, SchemaError
from scripts.rc022_mcp_negotiation_probe import observe, cases


def test_current_discover_dispatch_defaults_and_projection():
    value=parse('ModernDiscoverResultSchema',dict(supportedVersions=['2026-07-28'],capabilities={},ttlMs=-1,cacheScope='wrong',extra=True),RESOURCE_SCHEMAS)
    assert value==dict(supportedVersions=['2026-07-28'],capabilities={},ttlMs=0,cacheScope='private',extra=True)
    assert parse('ModernDiscoverResultSchema',dict(value,resultType='complete'),RESOURCE_SCHEMAS)['resultType']=='complete'
    # The wire dispatch schema admits extensions, including this public-schema field.
    assert parse('ModernDiscoverResultSchema',dict(value,resultType='wrong'),RESOURCE_SCHEMAS)['resultType']=='wrong'
    with pytest.raises(SchemaError):parse('ModernDiscoverResultSchema',dict(value,supportedVersions=[1]),RESOURCE_SCHEMAS)


def test_recursive_json_invalid_children_are_not_silently_accepted():
    with pytest.raises(SchemaError):parse('value',{'nested':[float('inf')]},{'schemas':{'value':{'type':'json-value'}}})


def test_paired_corpus_executes_all_contexts():
    rows=asyncio.run(observe())
    assert len(rows)==len(cases())==648
    assert {row['kind'] for row in rows}=={'modern','legacy','corrective','error'}


def test_auth_required_preserves_error_identity():
    error=SdkError('AUTH','denied')
    assert classify_probe_outcome(dict(kind='auth-required',error=error),{})['error'] is error
