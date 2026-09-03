"""
Layered environment snapshot and secure .env discovery (`@deepseek-ai/dsh-launch-environment` & `@deepseek-ai/dsh-home-paths`).
Resolves inherited process environment, project-level `<cwd>/.env`, and user-level `$DSH_HOME/.env`
with security tripwires against bootstrap variable injection.
"""

import os
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple


def expand_home_path(path: str) -> str:
    """Expand '~' or '~/' or '~\\' to the user home directory matching TS expandHomePath."""
    if path == "~":
        return os.path.expanduser("~")
    if path.startswith("~/") or path.startswith("~\\"):
        return os.path.join(os.path.expanduser("~"), path[2:])
    return path


def resolve_dsh_home(custom_home: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> str:
    """
    Resolve the Harness home directory ($DSH_HOME or ~/.dsh), expanding ~ if present.
    """
    if custom_home and isinstance(custom_home, str) and custom_home.strip():
        selected = custom_home.strip()
    else:
        env_dict = env if isinstance(env, dict) else os.environ
        env_home = env_dict.get("DSH_HOME")
        if env_home and isinstance(env_home, str) and env_home.strip():
            selected = env_home.strip()
        else:
            selected = os.path.join(os.path.expanduser("~"), ".dsh")
    return os.path.abspath(expand_home_path(selected))


# Exact variable names that cannot be set by discovered .env files
BOOTSTRAP_NAMES: Set[str] = {
    # Process launch and runtime resolution
    "PATH", "HOME", "USERPROFILE", "SHELL",
    "NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS",
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT",
    # Interpreter startup hooks
    "BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS",
    "PERL5OPT", "PERL5LIB", "PYTHONSTARTUP", "PYTHONPATH", "PYTHONHOME",
    "RUBYOPT", "RUBYLIB", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS",
    # Version control hooks, editors, pagers
    "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_PAGER", "GIT_EDITOR",
    "GIT_ASKPASS", "SSH_ASKPASS",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT",
    "EDITOR", "VISUAL", "PAGER", "BROWSER",
    # Network reach and trust
    "DEEPSEEK_BASE_URL", "DEEPSEEK_SEARCH_BASE_URL",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    "NODE_TLS_REJECT_UNAUTHORIZED",
}

# Prefix patterns forbidden in .env files
BOOTSTRAP_PREFIXES: Tuple[str, ...] = ("DSH_", "XDG_", "DYLD_", "BASH_FUNC_")


def is_bootstrap_only(name: str) -> bool:
    """
    Whether a variable may come ONLY from the inherited launch environment.
    """
    upper = name.upper()
    if upper in BOOTSTRAP_NAMES:
        return True
    for prefix in BOOTSTRAP_PREFIXES:
        if upper.startswith(prefix):
            return True
    return False


def parse_dotenv(content: str) -> Dict[str, str]:
    """
    Parse dotenv formatted text safely into key-value pairs.
    Supports multiline quoted values, inline comments, and single-pass double-quote unescaping.
    """
    entries: Dict[str, str] = {}
    lines = content.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        raw_line = lines[i]
        line = raw_line.strip()
        i += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") and len(line) > 7:
            line = line[7:].strip()

        if "=" not in line:
            continue

        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if not key:
            continue

        if val.startswith('"'):
            # Double-quoted (may be multiline)
            collected = [val[1:]]
            closed = False
            cur = collected[0]
            if len(cur) >= 1 and cur.endswith('"') and not cur.endswith('\\"'):
                collected[0] = cur[:-1]
                closed = True
            while not closed and i < n:
                next_line = lines[i]
                i += 1
                if next_line.endswith('"') and not next_line.endswith('\\"'):
                    collected.append(next_line[:-1])
                    closed = True
                else:
                    collected.append(next_line)
            combined = "\n".join(collected)
            esc_map = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
            entries[key] = re.sub(r'\\([\\ntr"])', lambda m: esc_map.get(m.group(1), m.group(0)), combined)
        elif val.startswith("'"):
            # Single-quoted (literal, may be multiline)
            collected = [val[1:]]
            closed = False
            cur = collected[0]
            if len(cur) >= 1 and cur.endswith("'"):
                collected[0] = cur[:-1]
                closed = True
            while not closed and i < n:
                next_line = lines[i]
                i += 1
                if next_line.endswith("'"):
                    collected.append(next_line[:-1])
                    closed = True
                else:
                    collected.append(next_line)
            entries[key] = "\n".join(collected)
        else:
            # Unquoted: strip inline comment after whitespace
            val_clean = re.split(r'\s+#', val, maxsplit=1)[0].strip()
            entries[key] = val_clean

    return entries


class LaunchEnvironmentEntry:
    """A resolved environment variable entry with its origin source layer."""

    def __init__(self, value: str, source: str, path: Optional[str] = None):
        self.value = value
        self.source = source  # 'process', 'project-env', 'user-env'
        self.path = path

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {"value": self.value, "source": self.source}
        if self.path is not None:
            res["path"] = self.path
        return res


SOURCE_ORDER: List[str] = ["process", "project-env", "user-env"]


class LaunchEnvironmentSnapshot:
    """
    Immutable snapshot of layered environment sources.
    """

    def __init__(self, layers: List[Dict[str, Any]]):
        self._layers: Dict[str, Dict[str, str]] = {}
        self._paths: Dict[str, str] = {}

        for layer in layers:
            src = layer["source"]
            vals = dict(layer.get("values", {}))
            folded: Dict[str, str] = {}
            for k, v in vals.items():
                lookup_key = k.upper() if sys.platform == "win32" else k
                folded[lookup_key] = v
            self._layers[src] = folded
            if "path" in layer and layer["path"]:
                self._paths[src] = layer["path"]

    def get_from(self, name: str, sources: Optional[List[str]] = None) -> Optional[LaunchEnvironmentEntry]:
        lookup = name.upper() if sys.platform == "win32" else name
        allowed = sources or SOURCE_ORDER
        for src in SOURCE_ORDER:
            if src not in allowed:
                continue
            if src in self._layers and lookup in self._layers[src]:
                val = self._layers[src][lookup]
                p = self._paths.get(src)
                return LaunchEnvironmentEntry(value=val, source=src, path=p)
        return None

    def get(self, name: str) -> Optional[LaunchEnvironmentEntry]:
        return self.get_from(name, SOURCE_ORDER)

    def get_value(self, name: str, default: Optional[str] = None) -> Optional[str]:
        entry = self.get(name)
        return entry.value if entry else default


LAUNCH_ENVIRONMENT_KEY: str = "launch_environment"


def launch_environment_of(ctx: Any) -> LaunchEnvironmentSnapshot:
    """
    Get the launch environment snapshot from context, falling back to process-only snapshot matching TS launchEnvironmentOf.
    """
    if hasattr(ctx, "get"):
        res = ctx.get(LAUNCH_ENVIRONMENT_KEY)
        if isinstance(res, LaunchEnvironmentSnapshot):
            return res
    return LaunchEnvironmentSnapshot([{"source": "process", "values": dict(os.environ)}])


def read_env_layer(bin_name: str, dir_path: str) -> Optional[Dict[str, Any]]:
    """
    Read and validate a single directory's .env file.
    Rejects any file declaring bootstrap-only variable names.
    """
    env_file = os.path.join(dir_path, ".env")
    if not os.path.isfile(env_file):
        return None

    try:
        with open(env_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        sys.stderr.write(f"[{bin_name} Warning] Failed to read {env_file}: {e}\n")
        return None

    values = parse_dotenv(content)
    for name in values.keys():
        if is_bootstrap_only(name):
            raise ValueError(
                f"{bin_name}: {env_file} sets \"{name}\", which only the launching environment may set "
                f"(it decides how this process starts, where its code and instructions load from, or how it "
                f"reaches the network); export {name} instead of putting it in a .env file"
            )

    return {"path": env_file, "values": values}


def load_layered_env(
    bin_name: str = "dsh",
    cwd: Optional[str] = None,
    custom_home: Optional[str] = None,
) -> LaunchEnvironmentSnapshot:
    """
    Discover and load layered environment snapshot:
    1. Process environment (os.environ)
    2. Project directory (.env)
    3. User home ($DSH_HOME/.env)
    """
    work_dir = os.path.abspath(cwd or os.getcwd())
    home_dir = resolve_dsh_home(custom_home)

    inherited = dict(os.environ)

    # 1. Parse both project and user .env files first
    project_layer = read_env_layer(bin_name, work_dir)
    user_layer = None
    if os.path.normcase(home_dir) != os.path.normcase(work_dir):
        user_layer = read_env_layer(bin_name, home_dir)

    # 2. Materialize non-bootstrap entries into os.environ if unset
    for layer in (project_layer, user_layer):
        if layer and "values" in layer:
            for k, v in layer["values"].items():
                if k not in os.environ:
                    os.environ[k] = v

    layers: List[Dict[str, Any]] = [{"source": "process", "values": inherited}]
    if project_layer:
        layers.append({"source": "project-env", "path": project_layer["path"], "values": project_layer["values"]})
    if user_layer:
        layers.append({"source": "user-env", "path": user_layer["path"], "values": user_layer["values"]})

    return LaunchEnvironmentSnapshot(layers)


def resolve_layered_config(
    ctx: Any,
    namespace: str,
    key: str,
    system_default: Any = None,
    preset_override: Any = None,
    cli_env_value: Any = None,
    workspace_value: Any = None,
) -> Any:
    """
    Configuration chain loading order (lowest to highest precedence):
    1. System Defaults
    2. Home Settings (~/.dsh/settings.yaml)
    3. Workspace Config
    4. Preset Overrides
    5. CLI / Env (Wins)
    """
    val = system_default

    # 2. Home Settings (~/.dsh/settings.yaml)
    if ctx and hasattr(ctx, "has") and ctx.has("settings"):
        settings_svc = ctx.get("settings")
        if hasattr(settings_svc, "get_setting"):
            home_val = settings_svc.get_setting(namespace, key)
            if home_val is not None:
                val = home_val

    # 3. Workspace Config
    if workspace_value is not None:
        val = workspace_value

    # 4. Preset Overrides
    if preset_override is not None:
        val = preset_override

    # 5. CLI / Env (Highest precedence)
    if cli_env_value is not None:
        val = cli_env_value

    return val

