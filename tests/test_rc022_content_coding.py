import hashlib
import importlib.metadata
import json
import random

import brotli
import pytest
import zstandard

from dsh.host.http_decode import brotliChunks, zstdChunks, contentCodings
from dsh.host.http_proxy import install_proxy_from_environment
from dsh.host.http_request import request
from scripts.oracles.http_proxy_current_python import Lookup
from scripts.rc022_content_coding_probe import observe
from test_http_proxy_install_current import network


@pytest.mark.asyncio
async def test_source_compressed_wire_and_coding_chain_corpus(tmp_path):
    rows=await observe()
    (tmp_path/'content-coding-observations.json').write_text(json.dumps(rows,ensure_ascii=True),encoding='utf-8')
    assert len(rows)==127
    encoded=json.dumps(rows,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode('utf-8')
    assert hashlib.sha256(encoded).hexdigest()=='9616cc291a8a0db728f2f8f13756dfafb3d8dbc70f3477a9055a91a016262c0c'


def test_expansion_and_literal_blocks_stay_bounded_and_preserve_first_frame():
    generator=random.Random(22)
    literal=bytes(generator.randrange(256) for _ in range(256*1024))
    for data in (b'A'*(2*1024*1024),literal):
        for encode,decode in ((brotli.compress,brotliChunks),(zstandard.ZstdCompressor().compress,zstdChunks)):
            wire=encode(data)
            parts=list(decode([wire+b'ignored trailer']))
            assert b''.join(parts)==data
            assert max(map(len,parts))<=65536
            assert len(parts)<=len(data)//16384+2
    assert contentCodings('gzip, unknown')==[]
    assert contentCodings('\x85gzip')==[]
    assert contentCodings('gzip,BR')==['br','gzip']


@pytest.mark.asyncio
async def test_https_installed_proxy_negotiates_all_qualified_codings(network):
    dispose=await install_proxy_from_environment(Lookup({'HTTP_PROXY':'http://localhost:'+str(network['proxy'].server_port)}),lambda _:None)
    try:
        for advertise in (False,True):
            async with request('https://origin.test/codings','GET',{},None,None,advertise_zstd=advertise) as (metadata,chunks):
                assert metadata['status']==200
                assert b''.join([chunk async for chunk in chunks])==b'ORIGIN'
        assert [row['headers']['Accept-Encoding'] for row in network['origins']]==['br, gzip, deflate','br, gzip, deflate, zstd']
    finally: await dispose()


def test_bundled_decoder_versions_are_pinned_for_both_architectures():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    for package,version in [('Brotli','1.2.1'),('zstandard','0.23.0')]:
        assert importlib.metadata.version(package)==version
        for filename in ('requirements-runtime.lock','requirements-runtime-x86.lock'):
            assert package+'=='+version in (root/filename).read_text(encoding='utf-8').splitlines()


def test_runtime_dependency_bundler_copies_complete_standalone_decoders(tmp_path):
    import subprocess
    import sys
    from scripts.build_portable import bundle_dependencies
    payload=tmp_path/'lib'
    bundle_dependencies([importlib.metadata.distribution(name) for name in ('Brotli','zstandard')],str(payload))
    source="import sys;sys.path.insert(0,sys.argv[1]);import brotli,zstandard;assert brotli.__file__.startswith(sys.argv[1]);assert zstandard.__file__.startswith(sys.argv[1]);assert brotli.decompress(brotli.compress(b'fixture'))==b'fixture';assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b'fixture'))==b'fixture'"
    subprocess.run([sys.executable,'-S','-c',source,str(payload)],check=True,timeout=15)
