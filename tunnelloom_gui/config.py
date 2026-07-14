from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .types import AppConfig


APP_DIR = Path(os.environ.get("XDG_CONFIG_HOME",
               Path.home() / ".config")) / "tunnelloom-gui"
CONFIG_FILE = APP_DIR / "config.json"

_ENV_SOFTETHER_DIR = os.environ.get("SOFTETHER_GUI_SOFTETHER_DIR", "")
COMMON_SOFTETHER_DIRS = tuple(
    item
    for item in (
        _ENV_SOFTETHER_DIR,
        "/usr/local/vpnclient",
        "/usr/vpnclient",
        "/opt/vpnclient",
        "/opt/tunnelloom-vpnclient",
        "/usr/lib/tunnelloom",
        "/usr/libexec/tunnelloom/vpnclient",
        str(Path.home() / "vpnclient"),
        str(Path.home() / "tunnelloom-vpnclient"),
    )
    if item
)

# These are deliberately narrow so automatic recovery remains fast and does not
# crawl the entire filesystem. They cover normal source and packaged installs.
DISCOVERY_ROOTS = (
    (Path("/usr/local"), 4),
    (Path("/opt"), 4),
    (Path.home(), 3),
)


def _first_program_file(candidates: Iterable[str]) -> str:
    """Find a SoftEther program even when only root may execute it."""
    for item in candidates:
        if not item:
            continue
        expanded = os.path.expanduser(item)
        if os.path.isabs(expanded):
            if Path(expanded).is_file():
                return os.path.realpath(expanded)
            continue
        found = shutil.which(expanded)
        if found:
            return os.path.realpath(found)
    return ""


def _executable_directories(executable: str) -> list[str]:
    if not executable:
        return []
    expanded = os.path.expanduser(executable)
    resolved = shutil.which(expanded) if not os.path.isabs(
        expanded) else expanded
    if not resolved:
        return []

    directories: list[str] = []
    for candidate in (str(Path(resolved).parent), str(Path(os.path.realpath(resolved)).parent)):
        normalized = os.path.abspath(os.path.expanduser(candidate))
        if normalized not in directories:
            directories.append(normalized)
    return directories


def _is_softether_directory(directory: str) -> bool:
    if not directory:
        return False
    path = Path(os.path.abspath(os.path.expanduser(directory)))
    return path.is_dir() and (path / "hamcore.se2").is_file()


def _walk_for_hamcore(root: Path, max_depth: int) -> Iterable[str]:
    try:
        root = root.expanduser().resolve()
    except OSError:
        return
    if not root.is_dir():
        return

    root_depth = len(root.parts)
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        if depth >= max_depth:
            directories[:] = []
        # Avoid unrelated caches and large development trees in the home folder.
        directories[:] = [
            name for name in directories
            if name not in {".cache", ".local", ".git", "node_modules", "venv", ".venv"}
        ]
        if "hamcore.se2" in files:
            yield str(current_path)


def discover_softether_directories() -> list[str]:
    found: list[str] = []
    for directory in COMMON_SOFTETHER_DIRS:
        normalized = os.path.abspath(os.path.expanduser(directory))
        if _is_softether_directory(normalized) and normalized not in found:
            found.append(normalized)
    for root, depth in DISCOVERY_ROOTS:
        for directory in _walk_for_hamcore(root, depth):
            normalized = os.path.abspath(directory)
            if normalized not in found:
                found.append(normalized)
    return found


def detect_softether_dir(
    vpncmd_path: str = "",
    vpnclient_path: str = "",
    configured_dir: str = "",
) -> str:
    candidates: list[str] = []
    if configured_dir:
        candidates.append(configured_dir)

    for executable in (
        vpncmd_path,
        vpnclient_path,
        shutil.which("vpncmd") or "",
        shutil.which("vpnclient") or "",
    ):
        candidates.extend(_executable_directories(executable))

    candidates.extend(COMMON_SOFTETHER_DIRS)
    candidates.extend(discover_softether_directories())

    seen: set[str] = set()
    for candidate in candidates:
        expanded = os.path.abspath(os.path.expanduser(candidate))
        if expanded in seen:
            continue
        seen.add(expanded)
        if _is_softether_directory(expanded):
            return expanded
    return ""


def detect_vpncmd(softether_dir: str = "") -> str:
    candidates: list[str] = []
    if softether_dir:
        candidates.append(
            str(Path(os.path.expanduser(softether_dir)) / "vpncmd"))
    candidates.extend(str(Path(item) / "vpncmd")
                      for item in COMMON_SOFTETHER_DIRS)
    candidates.append("vpncmd")
    return _first_program_file(candidates)


def detect_vpnclient(softether_dir: str = "") -> str:
    candidates: list[str] = []
    if softether_dir:
        candidates.append(
            str(Path(os.path.expanduser(softether_dir)) / "vpnclient"))
    candidates.extend(str(Path(item) / "vpnclient")
                      for item in COMMON_SOFTETHER_DIRS)
    candidates.append("vpnclient")
    return _first_program_file(candidates)


def repair_runtime_config(config: AppConfig) -> bool:
    """Repair stale paths left by older GUI versions or moved installations."""
    before = (config.softether_dir, config.vpncmd_path, config.vpnclient_path)

    directory = detect_softether_dir(
        config.vpncmd_path,
        config.vpnclient_path,
        config.softether_dir,
    )
    if directory:
        config.softether_dir = directory

        local_vpncmd = Path(directory) / "vpncmd"
        local_vpnclient = Path(directory) / "vpnclient"

        if local_vpncmd.is_file():
            config.vpncmd_path = str(local_vpncmd.resolve())
        elif not config.vpncmd_path or not Path(os.path.expanduser(config.vpncmd_path)).is_file():
            config.vpncmd_path = detect_vpncmd(directory)

        if local_vpnclient.is_file():
            config.vpnclient_path = str(local_vpnclient.resolve())
        elif not config.vpnclient_path or not Path(os.path.expanduser(config.vpnclient_path)).is_file():
            config.vpnclient_path = detect_vpnclient(directory)
    else:
        if not config.vpncmd_path:
            config.vpncmd_path = detect_vpncmd("")
        if not config.vpnclient_path:
            config.vpnclient_path = detect_vpnclient("")

    after = (config.softether_dir, config.vpncmd_path, config.vpnclient_path)
    return after != before


def load_config() -> AppConfig:
    config = AppConfig()
    if CONFIG_FILE.exists():
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for key in asdict(config):
                if key in raw:
                    setattr(config, key, raw[key])
        except (OSError, ValueError, TypeError):
            pass

    # Run on every startup, not only when the field is blank. Older versions may
    # have saved /usr/local/bin or another directory that does not contain
    # hamcore.se2. This migration silently repairs that stale value.
    changed = repair_runtime_config(config)
    if changed:
        try:
            save_config(config)
        except OSError:
            pass
    return config


def save_config(config: AppConfig) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(asdict(config), indent=2,
                    sort_keys=True), encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(CONFIG_FILE)
