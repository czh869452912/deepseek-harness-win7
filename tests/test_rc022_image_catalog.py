"""Semantic checks ensure paired observers reach the intended acceptance boundary."""
import pytest

from scripts.rc022_image_catalog_probe import image_rows, catalog_cases, catalog_row


def test_image_offload_is_immutable_atomic_and_reconstructible():
    rows={row['name']:row for row in image_rows()}
    for name,row in rows.items():
        if name.startswith('invalid-'):
            assert all(row[key]!='accepted' for key in ('append','resume','fold'))
            assert 'image/offload' in row['fold']
            assert row['seq']==1 and row['marked']==[False,False] and row['generation']==0
            assert row['after']==[False,True]
    identity=rows['identity']
    assert all(identity[key] for key in ('sameId','untouched','original','old','projected','fresh'))
    assert identity['nodes']==[0] and identity['position']==0 and identity['generation']==1
    assert identity['final']==[True,True] and identity['decisionMessage'] is None
    assert rows['replay']['parent']==rows['replay']['restored']==rows['replay']['resumed']==[True,True]
    assert rows['replay']['child']==[True,True,False,False]
    assert rows['atomic']['seq']==1 and rows['atomic']['generation']==0 and rows['atomic']['marked']==[False,False]
    assert 'already offloaded' in rows['atomic']['error']
    assert rows['tool']['marked']==[False,False,False,True] and 'error' not in rows['tool']
    assert 'already offloaded' in rows['repeat']['error']
    assert 'not a current surface node' in rows['shadowed']['error']
    assert 'must be user/message or tool/result' in rows['assistant']['error']


@pytest.mark.parametrize('row',catalog_cases(),ids=lambda row:row['name'])
def test_candidate_catalog_admission(row):
    result=catalog_row(row)
    if row['name'].startswith('version-'):
        version=row['header']['version']
        if version>4:assert result['classification']['status']=='unsupported' and 'error' in result
        elif version<4 and not row.get('children'):assert 'error' in result and 'children' in result['error']
        else:assert result['artifact']['header']['version']==4
    elif row['name']=='catalog-image':
        assert result['artifact']['events'][-1]['type']=='image/offload'
    elif row['name']=='lifecycle-valid' or row['name'].startswith('user/message-valid-current-'):
        assert 'artifact' in result and 'error' not in result
    elif row['name'].startswith('lifecycle-invalid-'):
        assert 'error' in result
        assert ('surfaceOp' if row['name'].endswith('surface') else 'does not exist') in result['error']
