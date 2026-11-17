"""Export-owned package image resources and cancellable disk streams."""
import asyncio
import os
import re
from pathlib import Path
from urllib.parse import unquote

from dsh.boot.package_resolution import resolve_plugin_resource
from dsh.host.client_modules.registry import IMMUTABLE_CACHE

ASSET_PATH=re.compile(r'^/plugins/(@[^/]+/[^/]+|[^@/][^/]*)/assets/(.*)$')
MEDIA_TYPES={'.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.jpg':'image/jpeg','.jpeg':'image/jpeg'}
REQUIRE_CONDITIONS=frozenset(('node','require','module-sync','node-addons'))


class FileBody:
    """Own an asynchronous open/read/close sequence, even before first pull."""
    def __init__(self,path):
        self.loop=asyncio.get_running_loop()
        self.opening=self.loop.run_in_executor(None,lambda:open(path,'rb'))
        self.reading=None
        self.closing=None
        self.closed=False
        # A caller can cancel before the first pull. Keep any open failure
        # observed while preserving it for a later pull or explicit close.
        self.opening.add_done_callback(lambda future:None if future.cancelled() else future.exception())

    def __aiter__(self):return self

    async def __anext__(self):
        if self.closed:raise StopAsyncIteration
        try:
            handle=await asyncio.shield(self.opening)
            if self.closed:raise StopAsyncIteration
            self.reading=self.loop.run_in_executor(None,handle.read,64*1024)
            data=await asyncio.shield(self.reading)
        except BaseException:
            await self.aclose()
            raise
        if not data:
            await self.aclose()
            raise StopAsyncIteration
        return data

    async def aclose(self):
        self.closed=True
        if self.closing is None:
            async def close():
                try:handle=await asyncio.shield(self.opening)
                except (OSError,ValueError):return
                try:
                    if self.reading is not None:await asyncio.shield(self.reading)
                finally:await self.loop.run_in_executor(None,handle.close)
            self.closing=asyncio.create_task(close())
        await asyncio.shield(self.closing)


def asset_response(method,record,asset_path,if_none_match):
    empty=dict(status=404,headers={},body=None)
    if record is None or not asset_path:return empty
    try:
        if re.search(r'%(?![0-9a-fA-F]{2})',asset_path):return empty
        decoded=unquote(asset_path,encoding='utf-8',errors='strict')
        # Node turns the export target into a file URL and decodes that path
        # again. A literal malformed percent (including one obtained from
        # %25) cannot name a file even when the filesystem has such a name.
        target_path=decoded.split('#',1)[0].split('?',1)[0]
        if re.search(r'%(?![0-9a-fA-F]{2})',target_path):return empty
        unquote(target_path,encoding='utf-8',errors='strict')
        path=resolve_plugin_resource(record['id']+'/assets/'+decoded,
            Path(record['meta']['manifest_path']).as_uri(),conditions=REQUIRE_CONDITIONS)
    except (ImportError,ValueError,OSError,UnicodeError):return empty
    name=os.path.basename(path);dot=name.rfind('.')
    media_type=MEDIA_TYPES.get(name[dot:].lower()) if dot>0 else None
    if media_type is None:return empty
    headers={'content-type':media_type,'cache-control':IMMUTABLE_CACHE,'etag':'"'+asset_path+'"','x-content-type-options':'nosniff'}
    if media_type=='image/svg+xml':headers['content-security-policy']="script-src 'none'"
    if if_none_match==headers['etag']:return dict(status=304,headers=headers,body=None)
    return dict(status=200,headers=headers,body=None if method=='HEAD' else FileBody(path))
