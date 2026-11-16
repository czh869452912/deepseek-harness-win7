import os
import pytest
from dsh.util.plugin_detail import LocalFiles,DetailFailure,detail_image,detail_image_response
from scripts.rc022_plugin_detail_probe import observe


@pytest.mark.asyncio
async def test_localized_document_reads_and_image_boundaries(tmp_path):
    rows=await observe(tmp_path)
    documents={row['name']:row for row in rows if row['kind']=='document'}
    assert documents['locale']['result']['value']==dict(origin='locale',path='guide/x.md',markdown='# Local')
    assert documents['fallback']['result']['value']['markdown']=='English'
    assert documents['case-order']['result']['value']['path']=='readme.md'
    assert documents['first-locale']['result']['value']['origin']=='readme'
    for mode in ('invalid','missing','null-detail'):assert documents[mode]['result']==dict(error='invalid')
    assert documents['too-large']['result']==dict(error='too-large')
    assert detail_image('docs/x.md','../../escape.png') is None
    assert detail_image('docs/x.md','../a.svg?rev=1')==dict(path='a.svg',mediaType='image/svg+xml')
    response=detail_image_response(dict(bytes=b'<svg/>',mediaType='image/svg+xml'),'private')
    assert response['status']==200 and response['headers']['Content-Security-Policy'].startswith('sandbox;')
    assert detail_image_response('too-large','private')['headers']['Cache-Control']=='no-store'


@pytest.mark.asyncio
async def test_local_detail_junction_cannot_leave_package_and_refreshes_bytes(tmp_path):
    root=tmp_path/'package';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir();(outside/'x.md').write_text('outside',encoding='utf-8')
    if os.name=='nt':
        import subprocess
        subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(root/'link'),str(outside)],check=True,capture_output=True)
    else:(root/'link').symlink_to(outside,target_is_directory=True)
    try:
        files=LocalFiles(str(root),'1')
        assert await files.read('link/x.md',100) is None
        path=root/'README.md';path.write_text('first',encoding='utf-8')
        assert await files.read('README.md',100)==b'first'
        path.write_text('second',encoding='utf-8')
        assert await files.read('README.md',100)==b'second'
        with pytest.raises(DetailFailure):await files.read('README.md',1)
    finally:
        if os.name=='nt':os.rmdir(str(root/'link'))
        else:(root/'link').unlink()
