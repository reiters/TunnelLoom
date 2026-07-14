from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from .config import CONFIG_FILE, load_config


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def permission_text(path: Path | None) -> str:
    if not path:
        return "(not set)"
    try:
        return stat.filemode(path.stat().st_mode)
    except OSError as exc:
        return f"unavailable ({exc})"


def path_is_file(path: Path | None) -> bool:
    try:
        return bool(path and path.is_file())
    except OSError:
        return False


def main() -> int:
    package_root = Path(__file__).resolve().parent.parent
    version_file = package_root / "VERSION"
    version = version_file.read_text(
        encoding="utf-8").strip() if version_file.is_file() else "unknown"
    config = load_config()

    softether_dir = Path(os.path.expanduser(
        config.softether_dir)).resolve() if config.softether_dir else None
    vpncmd = Path(os.path.expanduser(config.vpncmd_path)
                  ).resolve() if config.vpncmd_path else None
    vpnclient = Path(os.path.expanduser(config.vpnclient_path)
                     ).resolve() if config.vpnclient_path else None
    hamcore = softether_dir / "hamcore.se2" if softether_dir else None
    helper = Path("/usr/libexec/tunnelloom-gui-helper")

    loaded_module = Path(__file__).resolve()
    installed_root = Path("/opt/tunnelloom-gui").resolve()
    loaded_from_installed_tree = installed_root in loaded_module.parents

    print(f"GUI version: {version}")
    print(f"Loaded module: {loaded_module}")
    print(
        f"Loaded from installed application: {yes_no(loaded_from_installed_tree)}")
    print(f"Configuration file: {CONFIG_FILE}")
    print(f"Process working directory: {Path.cwd()}")
    print(f"Configured SoftEther directory: {softether_dir or '(not set)'}")
    print(
        f"SoftEther directory exists: {yes_no(bool(softether_dir and softether_dir.is_dir()))}")
    print(f"hamcore.se2: {hamcore or '(not set)'}")
    print(f"hamcore.se2 exists: {yes_no(path_is_file(hamcore))}")
    print(
        f"hamcore.se2 readable by desktop user: {yes_no(bool(hamcore and os.access(hamcore, os.R_OK)))} (not required)")
    print(f"hamcore.se2 permissions: {permission_text(hamcore)}")
    print(f"vpncmd: {vpncmd or '(not set)'}")
    print(f"vpncmd exists: {yes_no(path_is_file(vpncmd))}")
    print(
        f"vpncmd executable by desktop user: {yes_no(bool(vpncmd and os.access(vpncmd, os.X_OK)))} (not required)")
    print(f"vpncmd permissions: {permission_text(vpncmd)}")
    print(f"vpnclient: {vpnclient or '(not set)'}")
    print(f"vpnclient exists: {yes_no(path_is_file(vpnclient))}")
    print(f"PolicyKit helper: {helper}")
    print(
        f"PolicyKit helper installed: {yes_no(helper.is_file() and os.access(helper, os.X_OK))}")
    print(f"pkexec installed: {yes_no(bool(shutil.which('pkexec')))}")
    print("SoftEther file permissions modified by this GUI: no")
    print("vpncmd execution: persistent PolicyKit administrator helper session")
    print(
        f"privileged launch form: cd {softether_dir or '(not set)'} && ./vpncmd ...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
