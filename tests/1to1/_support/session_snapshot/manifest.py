"""
Parse and validate one recorded-session snapshot manifest.
Ported 1:1 from reference packages/test-support/session-snapshot/src/manifest.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import os
import re
from typing import Any, Dict, List, Optional, Set

import yaml

PROFILES: Set[str] = {"headless", "sdk", "acp", "web"}
RECORDINGS: Set[str] = {"live", "authored"}
PLATFORMS: Set[str] = {"posix", "pwsh"}
PERMISSIONS: Set[str] = {"read-only", "workspace-write", "danger-full-access"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _record(value: Any, label: str) -> Dict[str, Any]:
    if value is None or not isinstance(value, dict) or isinstance(value, list):
        raise ValueError(f"{label} must be a mapping")
    return value


def _exact_keys(value: Dict[str, Any], allowed: List[str], label: str) -> None:
    unknown = sorted([k for k in value.keys() if k not in allowed])
    if unknown:
        raise ValueError(f"{label} has unknown field(s): {', '.join(unknown)}")


def _name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise ValueError(f"{label} must be a lower-kebab-case name")
    return value


def _scenario_source(value: Any, label: str) -> str:
    if not isinstance(value, str) or not all(NAME_RE.match(segment) for segment in value.split("/")):
        raise ValueError(f"{label} must be a lower-kebab-case name or corpus-relative path")
    return value


def _positive_indexes(value: Any, label: str) -> List[int]:
    if not isinstance(value, list) or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 for x in value) or len(set(value)) != len(value):
        raise ValueError(f"{label} must be an array of unique positive integers")
    return list(value)


class StrictSnapshotManifestLoader(yaml.SafeLoader):
    pass


StrictSnapshotManifestLoader.yaml_constructors = {
    k: v for k, v in yaml.SafeLoader.yaml_constructors.items()
    if not (isinstance(k, str) and ("js" in k or k.startswith("!")))
}


def parse_snapshot_manifest(source: str, path: str = "snapshot.yml") -> Dict[str, Any]:
    """
    Parse one snapshot.yml without admitting unsupported tags or unknown fields.
    """
    try:
        parsed = yaml.load(source, Loader=StrictSnapshotManifestLoader)
    except Exception as error:
        raise ValueError(f"session-snapshot: {path}: invalid YAML: {str(error)}")

    try:
        root = _record(parsed, "manifest")
        _exact_keys(root, [
            "version",
            "scenario",
            "profile",
            "composition",
            "recording",
            "header",
            "replay",
            "platform",
            "permission",
            "environment",
            "workspace",
            "input",
            "session",
        ], "manifest")
        if root.get("version") != 1:
            raise ValueError("manifest.version must equal 1")
        scenario = None if root.get("scenario") is None else _name(root["scenario"], "manifest.scenario")
        profile = root.get("profile")
        if not isinstance(profile, str) or profile not in PROFILES:
            raise ValueError("manifest.profile must be headless, sdk, acp, or web")

        composition = None if root.get("composition") is None else _name(root["composition"], "manifest.composition")
        recording = None
        if "recording" in root and root["recording"] is not None:
            rec = root["recording"]
            if not isinstance(rec, str) or rec not in RECORDINGS:
                raise ValueError("manifest.recording must be live or authored")
            recording = rec

        header = None
        if "header" in root and root["header"] is not None:
            val = _record(root["header"], "manifest.header")
            _exact_keys(val, [
                "class",
                "pin",
                "systemPromptSource",
                "toolSchemasSource",
                "childSystemPrompts",
                "childToolSchemas",
                "changes",
            ], "manifest.header")
            if val.get("pin") is not None and val["pin"] is not True:
                raise ValueError("manifest.header.pin must equal true when present")
            if val.get("changes") is not None:
                changes = val["changes"]
                if isinstance(changes, bool) or not isinstance(changes, int) or changes < 0:
                    raise ValueError("manifest.header.changes must be a non-negative integer")
            header_class = _name(val.get("class"), "manifest.header.class")
            sp_source = None if val.get("systemPromptSource") is None else _scenario_source(val["systemPromptSource"], "manifest.header.systemPromptSource")
            ts_source = None if val.get("toolSchemasSource") is None else _scenario_source(val["toolSchemasSource"], "manifest.header.toolSchemasSource")
            child_sp = None if val.get("childSystemPrompts") is None else _positive_indexes(val["childSystemPrompts"], "manifest.header.childSystemPrompts")
            child_ts = None if val.get("childToolSchemas") is None else _positive_indexes(val["childToolSchemas"], "manifest.header.childToolSchemas")
            changes_val = val.get("changes")

            header = {
                "class": header_class,
                **({"pin": True} if val.get("pin") is True else {}),
                **({"systemPromptSource": sp_source} if sp_source is not None else {}),
                **({"toolSchemasSource": ts_source} if ts_source is not None else {}),
                **({"childSystemPrompts": child_sp} if child_sp is not None else {}),
                **({"childToolSchemas": child_ts} if child_ts is not None else {}),
                **({"changes": int(changes_val)} if changes_val is not None else {}),
            }

        replay = None
        if "replay" in root and root["replay"] is not None:
            r_val = _record(root["replay"], "manifest.replay")
            _exact_keys(r_val, ["override"], "manifest.replay")
            if r_val.get("override") is not True:
                raise ValueError("manifest.replay.override must equal true")
            replay = {"override": True}

        platform = None
        if "platform" in root and root["platform"] is not None:
            p_val = root["platform"]
            if not isinstance(p_val, str) or p_val not in PLATFORMS:
                raise ValueError("manifest.platform must be posix or pwsh")
            platform = p_val

        permission = None
        if "permission" in root and root["permission"] is not None:
            perm_val = root["permission"]
            if not isinstance(perm_val, str) or perm_val not in PERMISSIONS:
                raise ValueError("manifest.permission must be read-only, workspace-write, or danger-full-access")
            permission = perm_val

        environment = None
        if "environment" in root and root["environment"] is not None:
            env_val = _record(root["environment"], "manifest.environment")
            environment = {}
            for k, v in env_val.items():
                if not isinstance(k, str) or not re.match(r"^[A-Z][A-Z0-9_]*$", k) or not isinstance(v, str):
                    raise ValueError("manifest.environment must map uppercase environment names to strings")
                environment[k] = v

        workspace = None
        if "workspace" in root and root["workspace"] is not None:
            w_val = _record(root["workspace"], "manifest.workspace")
            _exact_keys(w_val, ["setup", "final", "parent"], "manifest.workspace")
            if w_val.get("final") is not None and w_val["final"] is not True:
                raise ValueError("manifest.workspace.final must equal true when present")
            if w_val.get("parent") is not None and w_val["parent"] != "home":
                raise ValueError("manifest.workspace.parent must equal home")
            setup_val = None if w_val.get("setup") is None else _name(w_val["setup"], "manifest.workspace.setup")
            workspace = {
                **({"setup": setup_val} if setup_val is not None else {}),
                **({"final": True} if w_val.get("final") is True else {}),
                **({"parent": "home"} if w_val.get("parent") == "home" else {}),
            }
            if len(workspace) == 0:
                raise ValueError("manifest.workspace must not be empty")

        input_data = None
        if "input" in root and root["input"] is not None:
            i_val = _record(root["input"], "manifest.input")
            _exact_keys(i_val, ["task", "attachments"], "manifest.input")
            task_val = i_val.get("task")
            if task_val is not None and (not isinstance(task_val, str) or task_val.strip() == ""):
                raise ValueError("manifest.input.task must be a non-empty string when present")
            attachments_val = i_val.get("attachments")
            attachments_list = None
            if attachments_val is not None:
                if not isinstance(attachments_val, list) or len(attachments_val) == 0:
                    raise ValueError("manifest.input.attachments must be a non-empty array")
                attachments_list = []
                for index, item in enumerate(attachments_val):
                    attachment = _record(item, f"manifest.input.attachments[{index}]")
                    _exact_keys(attachment, ["id", "mediaType", "data"], f"manifest.input.attachments[{index}]")
                    att_id = attachment.get("id")
                    if not isinstance(att_id, str) or not att_id.startswith("sha256:"):
                        raise ValueError(f"manifest.input.attachments[{index}].id must start with sha256:")
                    att_media = attachment.get("mediaType")
                    if not isinstance(att_media, str) or "/" not in att_media:
                        raise ValueError(f"manifest.input.attachments[{index}].mediaType must be a MIME type")
                    att_data = attachment.get("data")
                    if not isinstance(att_data, str) or len(att_data) == 0:
                        raise ValueError(f"manifest.input.attachments[{index}].data must be non-empty base64")
                    attachments_list.append({
                        "id": att_id,
                        "mediaType": att_media,
                        "data": att_data,
                    })
                if len(set(a["id"] for a in attachments_list)) != len(attachments_list):
                    raise ValueError("manifest.input.attachments must have unique ids")

            if task_val is None and attachments_list is None:
                raise ValueError("manifest.input must declare task or attachments")
            input_data = {
                **({"task": task_val} if task_val is not None else {}),
                **({"attachments": attachments_list} if attachments_list is not None else {}),
            }

        session_ref = None
        if "session" in root and root["session"] is not None:
            s_val = _record(root["session"], "manifest.session")
            _exact_keys(s_val, ["source"], "manifest.session")
            src = s_val.get("source")
            if not isinstance(src, str) or src.strip() == "":
                raise ValueError("manifest.session.source must be a non-empty string")
            if src.startswith("/") or "\\" in src or "\0" in src or os.path.isabs(src):
                raise ValueError("manifest.session.source must be a relative POSIX path")
            session_ref = {"source": src}

        return {
            "version": 1,
            **({"scenario": scenario} if scenario is not None else {}),
            "profile": profile,
            **({"composition": composition} if composition is not None else {}),
            **({"recording": recording} if recording is not None else {}),
            **({"header": header} if header is not None else {}),
            **({"replay": replay} if replay is not None else {}),
            **({"platform": platform} if platform is not None else {}),
            **({"permission": permission} if permission else {}),
            **({"environment": environment} if environment is not None else {}),
            **({"workspace": workspace} if workspace is not None else {}),
            **({"input": input_data} if input_data is not None else {}),
            **({"session": session_ref} if session_ref is not None else {}),
        }
    except Exception as exc:
        raise ValueError(f"session-snapshot: {path}: {str(exc)}")


parseSnapshotManifest = parse_snapshot_manifest
