"""Read current profile composition from launcher-owned locations."""
import copy
import os
from dsh.boot.profile import load_profile_directory, compose_entries, PROFILE_PATCH_FILENAME
from dsh.boot.runtime_resolution import _field

TELEMETRY_ROW_ID = 'session-telemetry-otel'


def resolve_telemetry_patch(disabled_env, has_row):
    if disabled_env in (None, '') or not has_row:
        return None
    return dict(id=TELEMETRY_ROW_ID, disabled=True)


def read_bundle_patches(bin_name, context, initial_profile=None):
    profile = initial_profile if initial_profile is not None else load_profile_directory(
        bin_name, _field(context, 'dir'), _field(context, 'installAnchor'), dict(userLayer=False))
    return [patch for layer in _field(profile, 'layers', []) for patch in _field(layer, 'patches', [])]


def read_profile_patches(bin_name, context, initial_profile=None):
    from dsh.boot.app_boot import load_optional_patches
    bundle_patches = read_bundle_patches(bin_name, context, initial_profile)
    user = _field(initial_profile, 'patches') if initial_profile is not None else None
    if user is None:
        user = load_optional_patches(bin_name, _field(context, 'patchPath')) or []
    patches = copy.deepcopy([
        *bundle_patches,
        *user,
        *(load_optional_patches(bin_name, os.path.join(_field(context, 'home'), PROFILE_PATCH_FILENAME)) or []),
        *_field(context, 'overlays', []),
    ])
    telemetry = resolve_telemetry_patch(_field(context, 'telemetryDisabledEnv'),
        any(row.get('id') == TELEMETRY_ROW_ID for row in compose_entries([patches])))
    if telemetry is not None:
        patches.append(telemetry)
    return patches


readBundlePatches = read_bundle_patches
readProfilePatches = read_profile_patches
resolveTelemetryPatch = resolve_telemetry_patch
