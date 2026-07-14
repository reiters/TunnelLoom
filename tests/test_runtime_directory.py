from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tunnelloom_gui.backend import SoftEtherBackend
from tunnelloom_gui.config import detect_softether_dir
from tunnelloom_gui.types import AppConfig, VirtualNic, VpnAccount


def test_detect_softether_directory_from_executable(tmp_path: Path) -> None:
    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir()
    (program_dir / "hamcore.se2").write_bytes(b"test")
    vpncmd = program_dir / "vpncmd"
    vpncmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    vpncmd.chmod(0o755)

    assert detect_softether_dir(str(vpncmd), "") == str(program_dir)


def test_vpncmd_request_uses_configured_softether_directory(tmp_path: Path, monkeypatch) -> None:
    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir()
    vpncmd = program_dir / "vpncmd"
    vpncmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    vpncmd.chmod(0o700)

    captured: dict[str, object] = {}
    backend = SoftEtherBackend(
        AppConfig(
            softether_dir=str(program_dir),
            vpncmd_path=str(vpncmd),
            vpnclient_path=str(program_dir / "vpnclient"),
        )
    )

    def fake_request(payload, timeout, commands=()):
        captured["payload"] = payload
        captured["timeout"] = timeout
        return __import__("softether_gui.types", fromlist=["CommandResult"]).CommandResult(
            0, "Command completed successfully.\n", "", commands
        )

    monkeypatch.setattr(backend, "_privileged_request", fake_request)
    result = backend._run_batch(["AccountList"], timeout=5, secrets=())

    assert result.returncode == 0
    payload = captured["payload"]
    assert payload["softether_dir"] == str(program_dir)
    assert payload["vpncmd_path"] == str(vpncmd)
    assert payload["commands"] == ["AccountList"]


def test_client_helper_arguments_preserve_empty_positions() -> None:
    backend = SoftEtherBackend(AppConfig(softether_dir="/usr/local/vpnclient"))
    assert backend._client_helper_args() == ["", "/usr/local/vpnclient"]


def test_repair_stale_configured_directory(tmp_path: Path, monkeypatch) -> None:
    from tunnelloom_gui import config as config_module
    from tunnelloom_gui.config import repair_runtime_config

    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir()
    (program_dir / "hamcore.se2").write_bytes(b"test")
    for name in ("vpncmd", "vpnclient"):
        executable = program_dir / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(
        config_module, "COMMON_SOFTETHER_DIRS", (str(program_dir),))
    monkeypatch.setattr(config_module, "DISCOVERY_ROOTS", ())
    app_config = AppConfig(
        softether_dir="/usr/local/bin",
        vpncmd_path="/missing/vpncmd",
        vpnclient_path="/missing/vpnclient",
    )

    assert repair_runtime_config(app_config)
    assert app_config.softether_dir == str(program_dir)
    assert app_config.vpncmd_path == str(program_dir / "vpncmd")
    assert app_config.vpnclient_path == str(program_dir / "vpnclient")


def test_validate_repairs_stale_directory_before_running(tmp_path: Path, monkeypatch) -> None:
    from tunnelloom_gui import config as config_module

    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir()
    (program_dir / "hamcore.se2").write_bytes(b"test")
    for name in ("vpncmd", "vpnclient"):
        executable = program_dir / name
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    monkeypatch.setattr(
        config_module, "COMMON_SOFTETHER_DIRS", (str(program_dir),))
    monkeypatch.setattr(config_module, "DISCOVERY_ROOTS", ())
    monkeypatch.setattr(
        "tunnelloom_gui.backend.save_config", lambda _config: None)

    app_config = AppConfig(
        softether_dir="/wrong/folder",
        vpncmd_path="/wrong/vpncmd",
        vpnclient_path="/wrong/vpnclient",
    )
    backend = SoftEtherBackend(app_config)
    backend.validate()

    assert backend.softether_dir == str(program_dir)
    assert backend.vpncmd_path == str(program_dir / "vpncmd")


def _helper_request(helper: Path, request: dict[str, object]) -> dict[str, object]:
    process = subprocess.Popen(
        [str(helper), "session"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(__import__("json").dumps(request) + "\n")
    process.stdin.flush()
    reply = __import__("json").loads(process.stdout.readline())
    process.stdin.write(__import__("json").dumps(
        {"id": 999, "action": "quit"}) + "\n")
    process.stdin.flush()
    process.wait(timeout=5)
    return reply


def test_privileged_helper_executes_local_vpncmd_after_chdir(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        __import__("pytest").skip(
            "privileged helper integration test requires root")
    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir(mode=0o755)
    (program_dir / "hamcore.se2").write_bytes(b"test")
    trace = tmp_path / "vpncmd-trace.txt"
    vpncmd = program_dir / "vpncmd"
    vpncmd.write_text(
        "#!/bin/sh\n"
        f"printf 'pwd=%s\nargv0=%s\n' \"$PWD\" \"$0\" > {trace!s}\n"
        "out=''\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in /OUT:*) out=${arg#/OUT:} ;; esac\n"
        "done\n"
        "[ -n \"$out\" ] && printf 'Command completed successfully.\n' > \"$out\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    vpncmd.chmod(0o755)
    vpnclient = program_dir / "vpnclient"
    vpnclient.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    vpnclient.chmod(0o755)

    helper = Path(__file__).resolve(
    ).parents[1] / "scripts" / "tunnelloom-gui-helper"
    reply = _helper_request(
        helper,
        {
            "id": 1,
            "action": "vpncmd-batch",
            "softether_dir": str(program_dir),
            "vpncmd_path": str(vpncmd),
            "host": "localhost",
            "commands": ["AccountList"],
            "timeout": 5,
        },
    )

    assert reply["returncode"] == 0, reply
    trace_text = trace.read_text(encoding="utf-8")
    assert f"pwd={program_dir}" in trace_text
    assert "argv0=./vpncmd" in trace_text


def test_privileged_helper_executes_local_vpnclient_after_chdir(tmp_path: Path) -> None:
    if os.geteuid() != 0:
        __import__("pytest").skip(
            "privileged helper integration test requires root")
    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir(mode=0o755)
    (program_dir / "hamcore.se2").write_bytes(b"test")
    trace = tmp_path / "vpnclient-trace.txt"
    vpncmd = program_dir / "vpncmd"
    vpncmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    vpncmd.chmod(0o755)
    vpnclient = program_dir / "vpnclient"
    vpnclient.write_text(
        "#!/bin/sh\n"
        f"printf 'pwd=%s\nargv0=%s\noperation=%s\n' \"$PWD\" \"$0\" \"${{1:-}}\" > {trace!s}\n",
        encoding="utf-8",
    )
    vpnclient.chmod(0o755)

    helper = Path(__file__).resolve(
    ).parents[1] / "scripts" / "tunnelloom-gui-helper"
    reply = _helper_request(
        helper,
        {
            "id": 2,
            "action": "status-client",
            "softether_dir": str(program_dir),
            "vpnclient_path": str(vpnclient),
            "timeout": 5,
        },
    )

    assert reply["returncode"] == 0, reply
    trace_text = trace.read_text(encoding="utf-8")
    assert f"pwd={program_dir}" in trace_text
    assert "argv0=./vpnclient" in trace_text
    assert "operation=status" in trace_text


def test_load_state_queries_all_existing_accounts_and_nics(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    calls: list[str] = []
    accounts = [object()]
    nics = [object()]

    monkeypatch.setattr(backend, "list_accounts",
                        lambda: calls.append("AccountList") or accounts)
    monkeypatch.setattr(backend, "list_nics",
                        lambda: calls.append("NicList") or nics)

    assert backend.load_state() == (accounts, nics)
    assert calls == ["AccountList", "NicList"]


def test_start_client_waits_then_loads_existing_state(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    calls: list[str] = []
    state = ([object()], [object()])

    monkeypatch.setattr(backend, "client_start", lambda: calls.append("start"))
    monkeypatch.setattr(backend, "wait_for_state", lambda **
                        _kwargs: calls.append("load") or state)

    assert backend.client_start_and_load_state() == state
    assert calls == ["start", "load"]


def test_wait_for_state_retries_until_vpncmd_is_ready(monkeypatch) -> None:
    from tunnelloom_gui.backend import VpncmdError

    backend = SoftEtherBackend(AppConfig())
    attempts = 0
    expected = ([VpnAccount(name="workaccount")], [VirtualNic(name="worknic")])

    def load_state():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise VpncmdError("not ready")
        return expected

    monkeypatch.setattr(backend, "load_state", load_state)
    monkeypatch.setattr("tunnelloom_gui.backend.time.sleep",
                        lambda _seconds: None)

    assert backend.wait_for_state(seconds=2, poll_interval=0) == expected
    assert attempts == 4


def test_validate_allows_root_only_hamcore(tmp_path: Path, monkeypatch) -> None:
    program_dir = tmp_path / "vpnclient"
    program_dir.mkdir()
    hamcore = program_dir / "hamcore.se2"
    hamcore.write_bytes(b"test")
    vpncmd = program_dir / "vpncmd"
    vpncmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    vpnclient = program_dir / "vpnclient"
    vpnclient.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    real_access = os.access

    def fake_access(path, mode):
        if os.fspath(path) in {str(hamcore), str(vpncmd), str(vpnclient)}:
            return False
        return real_access(path, mode)

    monkeypatch.setattr("tunnelloom_gui.backend.os.access", fake_access)
    backend = SoftEtherBackend(
        AppConfig(
            softether_dir=str(program_dir),
            vpncmd_path=str(vpncmd),
            vpnclient_path=str(vpnclient),
        )
    )

    backend.validate()


def test_authorize_opens_privileged_helper_session(monkeypatch) -> None:
    from tunnelloom_gui.types import CommandResult

    backend = SoftEtherBackend(AppConfig())
    captured: dict[str, object] = {}

    def fake_request(payload, timeout, commands=()):
        captured["payload"] = payload
        captured["timeout"] = timeout
        captured["commands"] = commands
        return CommandResult(0, "authorized", "", commands)

    monkeypatch.setattr(backend, "_privileged_request", fake_request)
    backend.authorize(timeout=12)

    assert captured["payload"] == {"action": "authorize"}
    assert captured["timeout"] == 12
    assert captured["commands"] == ("authorize",)


def test_privileged_helper_accepts_authorize_handshake() -> None:
    if os.geteuid() != 0:
        __import__("pytest").skip(
            "privileged helper integration test requires root")
    helper = Path(__file__).resolve(
    ).parents[1] / "scripts" / "tunnelloom-gui-helper"
    reply = _helper_request(
        helper, {"id": 3, "action": "authorize", "timeout": 5})

    assert reply["returncode"] == 0
    assert reply["output"] == "authorized"


def test_wait_for_state_does_not_accept_transient_empty_restart_snapshot(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    expected_account = VpnAccount(name="workaccount", status="Offline")
    expected_nic = VirtualNic(name="worknic", status="Enabled")
    snapshots = [
        ([], []),
        ([], []),
        ([expected_account], [expected_nic]),
        ([expected_account], [expected_nic]),
    ]

    monkeypatch.setattr(backend, "load_state", lambda: snapshots.pop(0))
    monkeypatch.setattr("tunnelloom_gui.backend.time.sleep",
                        lambda _seconds: None)

    state = backend.wait_for_state(
        seconds=5,
        poll_interval=0,
        expected_accounts=frozenset({"workaccount"}),
        expected_nics=frozenset({"worknic"}),
        settle_seconds=100,
    )

    assert state == ([expected_account], [expected_nic])
    assert snapshots == []


def test_wait_for_state_accepts_two_stable_snapshots_without_prior_names(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    expected = ([VpnAccount(name="new")], [VirtualNic(name="nic")])
    snapshots = [expected, expected]

    monkeypatch.setattr(backend, "load_state", lambda: snapshots.pop(0))
    monkeypatch.setattr("tunnelloom_gui.backend.time.sleep",
                        lambda _seconds: None)

    assert backend.wait_for_state(seconds=5, poll_interval=0) == expected
