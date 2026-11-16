import json
import traceback

import pytest
import yaml

from dsh.credentials.document_current import parse_credentials_document, render_flat_layout_migration
from scripts.rc022_credentials_document_probe import observe


@pytest.mark.asyncio
async def test_pinned_credentials_document_admission_corpus(tmp_path):
    rows = await observe(tmp_path/'parser-diagnostic-observations.json')
    (tmp_path/'credentials-document-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 379
    assert rows[13]['value']['refs'] == dict(YES='yes', ON='on', DATE='2026-11-17')
    assert rows[11]['value']['ignoredKeys'] == ['foreign']
    assert rows[15]['error'].endswith('is cyclic')


@pytest.mark.parametrize('body', ['refs: [DO_NOT_EXPOSE_THIS', 'refs: {KEY: "DO_NOT_EXPOSE_THIS}',
                                 'refs: {KEY: DO_NOT_EXPOSE_THIS, KEY: second}',
                                 'records: {owner/a: {kind: grant, payload: !!timestamp DO_NOT_EXPOSE_THIS}}'])
def test_yaml_failures_never_quote_secret_source_or_exception_context(body):
    text = 'version: 1\n'+body
    try: parse_credentials_document(text, '<private-document>')
    except ValueError as error:
        diagnostic = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        assert 'DO_NOT_EXPOSE_THIS' not in diagnostic
        assert str(error).startswith('credentials-local: invalid document at <private-document>: ')
    else: pytest.fail('malformed private document was admitted')


def test_alias_budget_includes_the_original_anchor_and_protects_ignored_data():
    def text(count): return 'version: 1\nforeign: {base: &x private, aliases: ['+', '.join(['*x']*count)+']}'
    assert parse_credentials_document(text(99), '<document>')['ignoredKeys'] == ['foreign']
    with pytest.raises(ValueError, match='Excessive alias count'):
        parse_credentials_document(text(100), '<document>')


def test_current_core_resolvers_do_not_change_other_yaml_consumers():
    assert yaml.safe_load('yes') is True
    result = parse_credentials_document('version: 1\nrefs: {KEY: yes}', '<document>')
    assert result['refs'] == dict(KEY='yes')
    assert yaml.safe_load('yes') is True


def test_flat_migration_retains_annotations_crlf_and_final_newline():
    text = '# annotation\r\nKEY: yes # key note\r\n\r\nSECOND: on'
    migrated = render_flat_layout_migration(text)
    assert migrated == 'version: 1\nrefs:\n  # annotation\r\n  KEY: yes # key note\r\n  \r\n  SECOND: on\n'
    assert parse_credentials_document(migrated, '<document>')['refs'] == dict(KEY='yes', SECOND='on')
    assert render_flat_layout_migration('KEY: &key secret\nSECOND: *key\n') is None


def test_legacy_merge_precedence_and_non_json_collection_admission():
    text = '%YAML 1.1\n---\nversion: 1\nforeign: &a {KEY: original}\nrefs: {KEY: replaced, <<: *a}'
    assert parse_credentials_document(text, '<document>')['refs'] == dict(KEY='replaced')
    assert parse_credentials_document('version: 1\nrefs: !!set {KEY: null}', '<document>')['refs'] == {}
    with pytest.raises(TypeError, match='holds a value JSON cannot represent'):
        parse_credentials_document('version: 1\nrecords: {owner/a: {kind: grant, payload: !!set {}}}', '<document>')
