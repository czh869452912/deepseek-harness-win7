"""
Cordis Config Watcher & HMR Service matching reference/vendor/hmr/src/index.ts.
Provides safe configuration watching, debouncing, serialized refreshes,
and 'hmr/config-update-failed' failure notification events.
"""

import asyncio
import inspect
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from dsh.cordis.context import Context
from dsh.cordis.service import Service


class ConfigRefreshState:
    def __init__(self):
        self.dirty: bool = False
        self.running: Optional[asyncio.Task] = None


class ConfigWatcherService(Service):
    """
    Configuration watching and change notification service matching TS Hmr.
    Provides register_config(), debouncing, serialized transactional reloads,
    and hmr/config-update-failed error event broadcast.
    """

    name = "hmr"

    def __init__(self, ctx: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(ctx, name="hmr")
        self.config = config or {}
        self.debounce_ms: float = float(self.config.get("debounce", 100))
        self._configs: Dict[str, Callable[[], Any]] = {}
        self._mtimes: Dict[str, float] = {}
        self._refreshes: Dict[str, ConfigRefreshState] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._running = True

        # Start background polling timer for portable zero-dependency Windows 7 file watching
        try:
            loop = asyncio.get_running_loop()
            self._poll_task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(max(0.1, self.debounce_ms / 1000.0))
                for filename, refresh_fn in list(self._configs.items()):
                    if not os.path.exists(filename):
                        continue
                    try:
                        mtime = os.path.getmtime(filename)
                    except OSError:
                        continue
                    last_mtime = self._mtimes.get(filename, 0.0)
                    if mtime > last_mtime:
                        self._mtimes[filename] = mtime
                        if last_mtime > 0:  # Skip initial check
                            self._trigger_refresh(filename, refresh_fn)
            except asyncio.CancelledError:
                break
            except Exception as e:
                if hasattr(self.ctx, "logger"):
                    self.ctx.logger("hmr").warn("Exception in config poll loop: %s", e)

    def _trigger_refresh(self, filename: str, refresh_fn: Callable[[], Any]) -> None:
        state = self._refreshes.setdefault(filename, ConfigRefreshState())
        state.dirty = True
        if state.running and not state.running.done():
            return

        async def _run() -> None:
            while state.dirty:
                state.dirty = False
                try:
                    res = refresh_fn()
                    if inspect.isawaitable(res):
                        await res
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").info("Reloaded config file %s", filename)
                except Exception as reason:
                    if hasattr(self.ctx, "logger"):
                        self.ctx.logger("hmr").warn("Config reload at %s failed: %s", filename, reason)
                    if hasattr(self.ctx, "parallel"):
                        try:
                            await self.ctx.parallel("hmr/config-update-failed", filename, reason)
                        except Exception:
                            pass

        try:
            loop = asyncio.get_running_loop()
            state.running = loop.create_task(_run())
        except RuntimeError:
            res = refresh_fn()
            if inspect.isawaitable(res):
                try:
                    asyncio.run(res)
                except Exception:
                    pass

    def register_config(self, filename: str, refresh_fn: Callable[[], Any]) -> Callable[[], None]:
        """
        Watch one exact config path and execute refresh_fn on modification matching TS hmr.registerConfig.
        """
        abs_path = os.path.abspath(filename)
        if os.path.exists(abs_path):
            self._mtimes[abs_path] = os.path.getmtime(abs_path)
        else:
            self._mtimes[abs_path] = time.time()

        self._configs[abs_path] = refresh_fn

        def unregister() -> None:
            self._configs.pop(abs_path, None)
            self._mtimes.pop(abs_path, None)
            self._refreshes.pop(abs_path, None)

        if hasattr(self.ctx, "effect"):
            return self.ctx.effect(unregister, label=f"hmr.register_config('{abs_path}')")
        return unregister

    def teardown(self) -> None:
        self._running = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._configs.clear()
        self._mtimes.clear()


# Backward-compatible and alias names
Hmr = ConfigWatcherService
HmrService = ConfigWatcherService
