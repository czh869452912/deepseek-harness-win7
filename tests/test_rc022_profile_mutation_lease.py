import asyncio
import json
from pathlib import Path
import subprocess
import sys

import pytest

from dsh.boot.profile_lease import ProfileLease,package_write_lease
from dsh.boot.profile_boot import INSTALL_ANCHOR
from dsh.boot import python_plugins as store
from test_python_plugin_distribution import profile,EXAMPLE,PACKAGE


def child(directory,exclusive=False):
    command=[sys.executable,'-c','from dsh.boot.profile_lease import ProfileLease;import sys;lease=ProfileLease(sys.argv[1],exclusive=sys.argv[2]=="1");print("acquired",flush=True)',str(directory),'1' if exclusive else '0']
    result=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=5)
    return result


def test_single_host_promotes_then_restores_shared_lease_and_stopped_installer_is_blocked(tmp_path):
    with ProfileLease(str(tmp_path)) as lease:
        assert child(tmp_path).returncode==0 and child(tmp_path,True).returncode!=0
        with lease.exclusive_window() as exclusive:
            assert exclusive is lease and lease.exclusive
            assert child(tmp_path).returncode!=0 and child(tmp_path,True).returncode!=0
            with pytest.raises(RuntimeError,match='nested'):
                with lease.exclusive_window():pytest.fail('nested mutation lease')
            with pytest.raises(RuntimeError,match='cannot close'):lease.close()
        assert not lease.exclusive and lease.stream is not None
        assert child(tmp_path).returncode==0 and child(tmp_path,True).returncode!=0
    assert child(tmp_path,True).returncode==0


def test_other_existing_host_refuses_promotion_without_losing_original_shared_lease(tmp_path):
    with ProfileLease(str(tmp_path)) as first,ProfileLease(str(tmp_path)) as second:
        original=first.stream
        with pytest.raises(RuntimeError,match='profile is in use'):
            with first.exclusive_window():pytest.fail('another host allowed mutation')
        assert first.stream is not None and not first.stream.closed and not first.exclusive
        assert original.closed and child(tmp_path,True).returncode!=0
    with ProfileLease(str(tmp_path),exclusive=True):pass


def test_another_process_read_lease_blocks_promotion_and_is_never_terminated(tmp_path):
    script='from dsh.boot.profile_lease import ProfileLease;import sys;lease=ProfileLease(sys.argv[1]);print("ready",flush=True);sys.stdin.readline()'
    process=subprocess.Popen([sys.executable,'-c',script,str(tmp_path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        assert process.stdout.readline()==(b'ready\r\n' if sys.platform=='win32' else b'ready\n')
        with ProfileLease(str(tmp_path)) as lease:
            with pytest.raises(RuntimeError,match='profile is in use'):
                with lease.exclusive_window():pytest.fail('external host allowed mutation')
            assert process.poll() is None and lease.stream is not None
    finally:
        process.communicate(b'close\n',timeout=5)
        for pipe in (process.stdin,process.stdout,process.stderr):pipe.close()
    assert process.returncode==0


def test_exception_restores_shared_lease_and_supplied_store_lease_does_not_transfer_ownership(profile):
    home,directory=profile
    with ProfileLease(str(directory)) as host:
        before=(directory/'package.json').read_bytes()
        with pytest.raises(RuntimeError,match='owned exclusive'):
            store.install(str(directory),str(EXAMPLE),INSTALL_ANCHOR,lease=host)
        assert (directory/'package.json').read_bytes()==before
        with pytest.raises(ValueError,match='deliberate'):
            with host.exclusive_window():
                assert store.install(str(directory),str(EXAMPLE),INSTALL_ANCHOR,lease=host)==PACKAGE
                assert host.stream is not None and host.exclusive
                store.uninstall(str(directory),PACKAGE,lease=host)
                raise ValueError('deliberate')
        assert host.stream is not None and not host.exclusive
        with pytest.raises(RuntimeError,match='profile is in use'):store.install(str(directory),str(EXAMPLE),INSTALL_ANCHOR)
    assert store.install(str(directory),str(EXAMPLE),INSTALL_ANCHOR)==PACKAGE
    store.uninstall(str(directory),PACKAGE)


def test_lease_capability_cannot_target_another_profile_or_be_a_boolean(tmp_path):
    with ProfileLease(str(tmp_path/'first'),exclusive=True) as lease:
        for supplied in (True,lease):
            with pytest.raises(RuntimeError):
                with package_write_lease(str(tmp_path/'second'),supplied):pytest.fail('foreign lease admitted')
    with pytest.raises(RuntimeError):
        with package_write_lease(str(tmp_path/'first'),lease):pytest.fail('closed lease admitted')


def test_process_exit_during_promotion_releases_both_os_locks(tmp_path):
    script='from dsh.boot.profile_lease import ProfileLease;import os,sys;lease=ProfileLease(sys.argv[1]);window=lease.exclusive_window();window.__enter__();os._exit(37)'
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,timeout=5)
    assert result.returncode==37
    with ProfileLease(str(tmp_path),exclusive=True):pass
