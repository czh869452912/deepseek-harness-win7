"""Explicit candidate runtime selection uses canonical overlay composition."""
from pathlib import Path
from dsh.boot.app_boot import load_overlay_patches
from dsh.boot.profile import compose_entries


def test_win7_overlay_keeps_original_identity_disabled_and_anchors_python():
    root=Path(__file__).resolve().parents[1]
    patches=load_overlay_patches('dsh',str(root/'migration/candidates/rc022/win7-runtime.patch.yml'))
    original=dict(id='ptc-runtime',name='@deepseek-ai/dsh-ptc-runtime-node',config={})
    rows=compose_entries([[dict(insert=[original])],patches])
    by_id={row['id']:row for row in rows}
    assert by_id['ptc-runtime']['name']==original['name'] and by_id['ptc-runtime']['disabled'] is True
    python=by_id['win7-ptc-runtime']
    expected=str(root/'dsh/code_runtime/confined_ptc.py')+':ConfinedPythonPtcRuntime'
    assert python['name']==expected and not python.get('disabled',False)
    assert 'disabled' not in original
