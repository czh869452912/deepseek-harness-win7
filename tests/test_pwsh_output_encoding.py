import codecs
from pathlib import Path

import pytest

from dsh.subprocess.collector import OutputCollector


@pytest.mark.parametrize('bom', [b'', codecs.BOM_UTF16_LE])
def test_fatal_host_stderr_decodes_without_nuls_and_keeps_raw_bytes(tmp_path, bom):
    text = 'Windows PowerShell 初始化失败\r\n'
    raw = bom + text.encode('utf-16-le')
    collector = OutputCollector(65536, 65536, 'stderr', str(tmp_path), text_encoding='powershell')
    collector.push(raw)
    collector.seal()
    value = collector.read_from(0)
    assert value.text == text
    assert value.nextOffset == len(raw)
    assert not value.lossy
    assert Path(value.spillPath).read_bytes() == raw
    assert collector.spill_fd is None


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16-le'])
def test_live_output_preserves_multibyte_characters_across_single_byte_chunks(tmp_path, encoding):
    text = 'Windows 中文输出 😀 完整\r\n'
    raw = text.encode(encoding)
    collector = OutputCollector(65536, 65536, 'stderr', str(tmp_path), text_encoding='powershell')
    offset, parts = 0, []
    for byte in raw:
        collector.push(bytes([byte]))
        value = collector.read_from(offset)
        offset = value.nextOffset
        parts.append(value.text)
    collector.seal()
    parts.append(collector.read_from(offset).text)
    assert ''.join(parts) == text
    if encoding == 'utf-16-le':
        assert Path(collector.spill_file).read_bytes() == raw


def test_generic_subprocess_utf8_contract_is_unchanged(tmp_path):
    raw = 'Windows 中文'.encode('utf-16-le')
    collector = OutputCollector(65536, None, 'stderr', str(tmp_path))
    collector.push(raw)
    assert collector.finalize().text == raw.decode('utf-8', 'replace')


@pytest.mark.parametrize('bom', [b'', codecs.BOM_UTF16_LE])
def test_truncated_fatal_stderr_remembers_encoding_and_preserves_complete_raw_log(tmp_path, bom):
    text = 'Windows PowerShell ' + '初始化失败' * 30
    raw = bom + text.encode('utf-16-le')
    collector = OutputCollector(10, 65536, 'stderr', str(tmp_path), text_encoding='powershell')
    # No reader polls until after the initial encoding evidence leaves the tail.
    for byte in raw:
        collector.push(bytes([byte]))
    value = collector.finalize()
    assert value.truncated
    assert value.text == text[-5:]
    assert Path(value.spillPath).read_bytes() == raw


def test_unconfirmed_codepage_is_escaped_without_guessing_gbk(tmp_path):
    raw = b'Windows ' + '初始化失败'.encode('cp936')
    collector = OutputCollector(65536, 65536, 'stderr', str(tmp_path), text_encoding='powershell')
    collector.push(raw)
    value = collector.finalize()
    assert '\ufffd' not in value.text
    assert '\\x' in value.text
    assert Path(value.spillPath).read_bytes() == raw


@pytest.mark.asyncio
async def test_real_redirected_child_preserves_fatal_stderr_and_exit_status(tmp_path):
    import sys
    from dsh.cordis.context import Context
    from dsh.subprocess import LocalSubprocessRuntime, SubprocessCollect, SubprocessSpawnSpec, SubprocessStdio
    ctx = Context()
    runtime = LocalSubprocessRuntime(ctx)
    text = 'Windows PowerShell 初始化失败\r\n'
    raw = text.encode('utf-16-le')
    code = 'import os,sys; os.write(2, bytes.fromhex(' + repr(raw.hex()) + ')); sys.exit(17)'
    try:
        handle = runtime.spawn(SubprocessSpawnSpec(
            argv=[sys.executable, '-c', code], cwd=str(tmp_path), grace_ms=1000,
            stdio=SubprocessStdio('ignore', SubprocessCollect(65536),
                SubprocessCollect(65536, {'maxBytes': 65536}, text_encoding='powershell'))))
        outcome = await handle.done
        value = handle.collected.stderr.read_from(0)
        assert outcome.exitCode == 17
        assert value.text == text
        assert Path(value.spillPath).read_bytes() == raw
    finally:
        await ctx.fiber.dispose()
