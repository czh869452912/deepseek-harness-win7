"""
Host Domain Handler (`@deepseek-ai/dsh-apiproxy/api/host`).
Handles `host.describe`, `host.pickDirectory`, `host.listDirectory`, `host.createDirectory`, `host.openPath`.
Aligned 1:1 with reference `api/host.ts`.
"""

import asyncio
import os
import subprocess
import sys
from typing import Any, Dict
from dsh.core.session import SessionStore


class HostDomainHandler:
    def __init__(self, ctx: Any, active_sessions: Dict[str, Any]):
        self.ctx = ctx
        self._active_sessions = active_sessions

    async def describe_host(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        llm = self.ctx.get("llm")
        plan_mode = self.ctx.get("plan_mode")
        goals = self.ctx.get("goals")
        sessions_svc: SessionStore = self.ctx.get("sessions")
        effective_model = llm.resolve_model() if llm else "deepseek-chat"
        effective_base_url = llm.resolve_base_url() if llm else "https://api.deepseek.com/v1"
        cwd_path = os.getcwd().replace("\\", "/")
        home_path = os.path.expanduser("~").replace("\\", "/")
        plan_active = plan_mode.is_active() if plan_mode else False
        curr_goal = goals.get_goal() if goals else None

        return {
            "status": "ready",
            "version": "0.1.0",
            "cwd": cwd_path,
            "provider": "deepseek",
            "model": effective_model,
            "baseUrl": effective_base_url,
            "planMode": plan_active,
            "goal": curr_goal.to_dict() if curr_goal else None,
            "attachedSessions": len(self._active_sessions),
            "sessionsCount": len(sessions_svc._sessions) if sessions_svc else 0,
            "home": home_path,
            "canOpenPath": True,
        }

    async def pick_directory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
        selected_path = None
        if dp:
            cap = dp.capability()
            if cap.get("kind") == "native":
                pick_fn = cap.get("pick")
                if asyncio.iscoroutinefunction(pick_fn):
                    selected_path = await pick_fn()
                elif callable(pick_fn):
                    selected_path = pick_fn()

        if selected_path:
            selected_path = os.path.normpath(selected_path).replace("\\", "/")
        return {"path": selected_path}

    async def list_directory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
        target_path = payload.get("path")
        if dp and dp.capability().get("kind") == "browse":
            return await dp.capability()["list"](target_path)

        p = os.path.abspath(target_path or os.path.expanduser("~"))
        home = os.path.abspath(os.path.expanduser("~"))
        crumbs = []
        curr = p
        while True:
            name = os.path.basename(curr) or curr
            crumbs.insert(0, {"name": name, "path": curr.replace("\\", "/"), "hidden": False})
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent

        entries = []
        try:
            for it in sorted(os.listdir(p)):
                full = os.path.join(p, it)
                if os.path.isdir(full):
                    entries.append({
                        "name": it,
                        "path": full.replace("\\", "/"),
                        "hidden": it.startswith("."),
                    })
        except Exception:
            pass

        return {
            "path": p.replace("\\", "/"),
            "home": home.replace("\\", "/"),
            "crumbs": crumbs,
            "entries": entries,
            "truncated": False,
        }

    async def create_directory(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        dp = self.ctx.get("directory_picker") or self.ctx.get("directoryPicker")
        p = payload.get("path", os.getcwd())
        n = payload.get("name", "New Folder")
        if dp and dp.capability().get("kind") == "browse":
            res_path = await dp.capability()["createDirectory"](p, n)
            return {"path": res_path.replace("\\", "/")}

        target = os.path.join(p, n)
        os.makedirs(target, exist_ok=False)
        return {"path": os.path.abspath(target).replace("\\", "/")}

    async def open_path(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target_path = payload.get("path")
        if target_path and os.path.exists(target_path):
            try:
                if sys.platform == "win32":
                    os.startfile(target_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", target_path])
                else:
                    subprocess.Popen(["xdg-open", target_path])
            except Exception:
                pass
        return {"opened": True}
