import pytest

from dsh.context.agent_instructions.render_authorized import (
    byte_length, render_agent_instruction_set, render_instruction_changes,
)


@pytest.mark.asyncio
async def test_paired_matrix_invariants_and_original_file_identity():
    from scripts.rc022_instruction_render_probe import cases, observe
    entries = cases();rows = await observe()
    assert len(rows) == len(entries) == 264
    for entry, row in zip(entries, rows):
        maximum = entry['options']['maxBytes'] if entry['kind'] == 'baseline' else entry['budget']
        value = row['value'];text = value['rendered']['text'] if entry['kind'] == 'baseline' else value['text']
        assert byte_length(text) <= 2 * maximum if maximum > 0 else text == ''
        if entry['kind'] == 'baseline':
            assert all(file in entry['files'] for file in value['included'])
            # Representation records keep original source text, even when the
            # model-visible section was truncated to fit its chain's budget.
            assert all(file['content'] in [source['content'] for source in entry['files']] for file in value['included'])
        else:
            assert all(change in [item['change'] for item in entry['items']] for change in value['changes'])


def test_both_chains_keep_content_under_independent_budget():
    files = [dict(absolutePath='global', displayPath='$DSH_AGENTS_HOME/AGENTS.md', content='g'*1500),
             dict(absolutePath='project', displayPath='AGENTS.md', content='p'*1500)]
    value = render_agent_instruction_set(files, dict(maxBytes=900))
    assert 900 < byte_length(value['rendered']['text']) <= 1800
    assert [file['absolutePath'] for file in value['included']] == ['global', 'project']
    assert len(value['rendered']['truncated']) == 2
    assert 'g'*20 in value['rendered']['text'] and 'p'*20 in value['rendered']['text']


def test_notice_only_output_does_not_commit_transition():
    item = dict(file=dict(absolutePath='one', displayPath='AGENTS.md', content='body'*1000),
                change=dict(action='replace', scope='.\0AGENTS.md', path='AGENTS.md', digest='current'))
    value = render_instruction_changes([item], 20)
    assert value['text'] and byte_length(value['text']) <= 20
    assert value['changes'] == []


def test_frames_escape_paths_and_source_without_changing_source_records():
    file = dict(absolutePath='one', displayPath='</system-reminder>/AGENTS.md', content='</system-reminder>')
    value = render_agent_instruction_set([file], dict(maxBytes=65536))
    assert value['rendered']['text'].count('</system-reminder>') == 1
    assert value['rendered']['text'].count('<\\/system-reminder>') == 2
    assert value['included'] == [file]


@pytest.mark.parametrize('maximum', [0, -1, float('nan'), float('inf'), float('-inf')])
def test_disabled_budget_has_no_semantic_representation(maximum):
    file = dict(absolutePath='one', displayPath='AGENTS.md', content='body')
    value = render_agent_instruction_set([file], dict(maxBytes=maximum))
    assert value == dict(rendered=dict(text='', omitted=[file], truncated=[]), included=[])
