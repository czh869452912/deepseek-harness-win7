import asyncio
import hashlib
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from dsh.attachment.store_current import CurrentLocalAttachmentStore
from dsh.attachment.local import request_image_variant_id
from scripts import rc022_image_targets_probe as corpus


@pytest.mark.asyncio
async def test_real_codec_target_cache_and_validation_corpus(tmp_path):
    corpus.prepare(tmp_path)
    rows=await corpus.observe()
    (tmp_path/'image-targets-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==23
    encoded=[row for row in rows if row['kind']=='encoded']
    assert all(row['sameAbortReason'] and row['repairEqual'] and row['identityStable'] and all(row['identityChanges']) and row['durableUnchanged'] for row in encoded)
    assert (encoded[0]['width'],encoded[0]['height'])==(1187,1386)
    assert sum(row['original'] for row in encoded)==2
    assert sum(not row['withinBytes'] for row in encoded)==2
    assert all(row.get('code')=='INVALID_ATTACHMENT_REF' for row in rows if row['kind']=='invalid')


@pytest.mark.asyncio
async def test_current_provider_shares_complete_target_identity_and_preserves_durable_source(tmp_path,monkeypatch):
    from dsh.attachment import images_current
    store=CurrentLocalAttachmentStore(config=dict(dshHome=str(tmp_path)))
    stream=io.BytesIO();Image.new('RGB',(1224,1429),(12,34,56)).save(stream,format='PNG')
    try:
        ref=await store.saveImage(dict(data=stream.getvalue(),mediaType='image/png'))
        path=Path(store.imageHostPath(ref));before=hashlib.sha256(path.read_bytes()).hexdigest()
        original=images_current.read_request_image;entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def held(root,stored,target,signal):
            calls.append(dict(target));entered.set();await release.wait()
            return await original(root,stored,target,signal)
        monkeypatch.setattr(images_current,'read_request_image',held)
        target=dict(width=1187,height=1386,maxBytes=2000000)
        one=asyncio.ensure_future(store.readImageRequest(ref,target))
        await entered.wait()
        two=asyncio.ensure_future(store.readImageRequest(ref,dict(reversed(list(target.items())))))
        await asyncio.sleep(0)
        release.set();first,second=await asyncio.gather(one,two)
        assert len(calls)==1 and first is second
        assert (first['width'],first['height'])==(1187,1386)
        other=await store.readImageRequest(ref,dict(target,width=1000,height=1167))
        assert len(calls)==2 and other['variantId']!=first['variantId']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==before
        assert not store._request_inflight
    finally:
        # The immutable source object is owned solely by this fixture.
        for parent,_,files in os.walk(str(tmp_path)):
            for name in files:os.chmod(os.path.join(parent,name),0o600)


def test_target_cache_identity_separates_equal_area_and_historical_policies():
    ref=dict(attachmentId='sha256:'+'a'*64)
    one=request_image_variant_id(ref,dict(width=100,height=25,maxBytes=10000))
    two=request_image_variant_id(ref,dict(width=50,height=50,maxBytes=10000))
    old=request_image_variant_id(ref,dict(maxPixels=2500,maxBytes=10000))
    assert len({one,two,old})==3
