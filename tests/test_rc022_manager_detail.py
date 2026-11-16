import pytest
from scripts.rc022_manager_detail_probe import observe


@pytest.mark.asyncio
async def test_manager_detail_remote_and_owned_image_route(tmp_path):
    rows=await observe(tmp_path)
    assert len(rows)==18
    assert rows[0]['result']['value']==dict(status='found',origin='locale',path='guide/DETAIL.zh.md',markdown='# Localized')
    assert rows[2]['result']['value']['origin']=='readme'
    assert rows[3]['result']['value']==dict(status='none')
    assert rows[4]['result']['error']==dict(code='plugin-manager/detail-unavailable',details=dict(reason='invalid'))
    assert rows[5]['result']['error']['code']=='plugin-manager/invalid-language'
    assert rows[6]['result']['error']['code']=='plugin-manager/unknown-bundle'
    assert rows[7]['result']['value']['markdown']=='# Offered'
    assert all(url.startswith('https://unpkg.com/') for url in rows[7]['requests'])
    images=[row['result'] for row in rows if row['kind']=='image']
    assert [image['status'] for image in images]==[400,200,404,404,200]
    assert images[1]['headers']['Content-Security-Policy'].startswith('sandbox;')
    assert next(row for row in rows if row['kind']=='fresh-image')['result']['body']=='<svg>new</svg>'
    assert next(row for row in rows if row['kind']=='image-limit')['result']['status']==413
    assert rows[-1]==dict(kind='disposed-route',remaining=[])
