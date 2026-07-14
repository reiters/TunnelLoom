from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

from tunnelloom_gui.backend import SoftEtherBackend
from tunnelloom_gui.types import AppConfig, VpnAccount


def load_helper():
    path = Path(__file__).resolve(
    ).parents[1] / "scripts" / "tunnelloom-gui-helper"
    loader = importlib.machinery.SourceFileLoader(
        "tunnelloom_gui_helper_test", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def completed(argv, code=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(argv, code, stdout, stderr)


def test_dhcpcd_acquires_ipv4_without_touching_resolver(monkeypatch):
    helper = load_helper()
    calls: list[list[str]] = []

    monkeypatch.setattr(helper, "nmcli_is_available", lambda: True)
    monkeypatch.setattr(helper, "remove_gui_nm_profiles", lambda interface: [])
    monkeypatch.setattr(helper.shutil, "which",
                        lambda name: "/usr/sbin/dhcpcd" if name == "dhcpcd" else None)

    def fake_run(argv, timeout=30):
        calls.append(argv)
        if argv[:6] == ["ip", "-4", "-o", "address", "show", "dev"]:
            return completed(argv, stdout=b"7: vpn_worknic inet 172.30.14.20/20 scope global vpn_worknic\n")
        return completed(argv, stdout=b"ok\n")

    monkeypatch.setattr(helper, "run_process", fake_run)
    result = helper.run_dhcp(
        {"id": 1, "interface": "vpn_worknic", "timeout": 30}, True)

    assert result["returncode"] == 0
    start_call = next(
        argv for argv in calls if argv and argv[0] == "dhcpcd" and "-w" in argv)
    assert start_call == [
        "dhcpcd", "-4", "-w", "-L", "-C", "resolv.conf", "-t", "30", "vpn_worknic"
    ]
    assert "172.30.14.20/20" in result["output"]


def test_dhcpcd_without_ipv4_is_reported_as_failure(monkeypatch):
    helper = load_helper()
    calls: list[list[str]] = []
    monkeypatch.setattr(helper, "nmcli_is_available", lambda: False)
    monkeypatch.setattr(helper.shutil, "which",
                        lambda name: "/usr/sbin/dhcpcd" if name == "dhcpcd" else None)

    def fake_run(argv, timeout=30):
        calls.append(argv)
        if argv[:6] == ["ip", "-4", "-o", "address", "show", "dev"]:
            return completed(argv)
        return completed(argv, stdout=b"ok\n")

    monkeypatch.setattr(helper, "run_process", fake_run)
    result = helper.run_dhcp(
        {"id": 8, "interface": "vpn_worknic", "timeout": 30}, True)

    assert result["returncode"] != 0
    assert "No IPv4 address" in result["stderr"]
    assert ["dhcpcd", "-4", "-C", "resolv.conf", "-k", "vpn_worknic"] in calls


def test_backend_disconnect_removes_softether_before_linux_network():
    backend = SoftEtherBackend(AppConfig(default_dhcp=True))
    calls: list[str] = []
    # type: ignore[method-assign]
    backend.run = lambda commands, **kwargs: calls.append(commands[0])
    backend.dhcp_stop = lambda interface, tolerate_errors=False: calls.append(
        f"dhcp-stop {interface}")  # type: ignore[method-assign]

    backend.disconnect(VpnAccount(name="workaccount",
                       nic="worknic", status="Connected"))

    assert calls == ['AccountDisconnect "workaccount"',
                     "dhcp-stop vpn_worknic"]


def test_network_repair_reloads_networkmanager_dns(monkeypatch):
    helper = load_helper()
    calls: list[list[str]] = []
    monkeypatch.setattr(helper, "nmcli_is_available", lambda: True)
    monkeypatch.setattr(helper, "active_base_connections",
                        lambda excluded_interface="": [])
    monkeypatch.setattr(helper, "default_route_present", lambda: True)

    def fake_run(argv, timeout=30):
        calls.append(argv)
        return completed(argv)

    monkeypatch.setattr(helper, "run_process", fake_run)
    result = helper.repair_network({"id": 2})

    assert result["returncode"] == 0
    assert ["nmcli", "general", "reload", "dns-rc"] in calls


def test_disconnect_releases_dhcpcd_without_resolver_hook(monkeypatch):
    helper = load_helper()
    calls: list[list[str]] = []
    monkeypatch.setattr(helper, "nmcli_is_available", lambda: True)
    monkeypatch.setattr(helper, "remove_gui_nm_profiles", lambda interface: [])
    monkeypatch.setattr(helper, "refresh_normal_network",
                        lambda excluded_interface="": [])
    monkeypatch.setattr(helper, "default_route_present", lambda: True)
    monkeypatch.setattr(helper, "resolver_nameservers",
                        lambda path: ["10.0.1.1"])
    monkeypatch.setattr(helper.shutil, "which",
                        lambda name: "/usr/sbin/dhcpcd" if name == "dhcpcd" else None)

    def fake_run(argv, timeout=30):
        calls.append(argv)
        return completed(argv)

    monkeypatch.setattr(helper, "run_process", fake_run)
    result = helper.run_dhcp({"id": 3, "interface": "vpn_worknic"}, False)

    assert result["returncode"] == 0
    assert ["dhcpcd", "-4", "-C", "resolv.conf", "-k", "vpn_worknic"] in calls
    assert ["dhcpcd", "-k", "vpn_worknic"] not in calls


def test_empty_dhcpcd_resolver_is_backed_up_and_linked_to_networkmanager(tmp_path, monkeypatch):
    helper = load_helper()
    etc = tmp_path / "resolv.conf"
    runtime_dir = tmp_path / "run" / "NetworkManager"
    runtime_dir.mkdir(parents=True)
    runtime = runtime_dir / "resolv.conf"
    backup = tmp_path / "resolv.conf.tunnelloom-gui-backup"
    etc.write_text("# Generated by dhcpcd\n", encoding="utf-8")
    runtime.write_text(
        "# Generated by NetworkManager\nnameserver 10.0.1.1\n", encoding="utf-8")
    monkeypatch.setattr(helper, "ETC_RESOLV_CONF", etc)
    monkeypatch.setattr(helper, "NM_RESOLV_CONF", runtime)
    monkeypatch.setattr(helper, "RESOLV_BACKUP", backup)

    messages = helper.point_resolver_to_networkmanager()

    assert etc.is_symlink()
    assert etc.resolve() == runtime
    assert helper.resolver_nameservers(etc) == ["10.0.1.1"]
    assert backup.read_text(encoding="utf-8") == "# Generated by dhcpcd\n"
    assert any("Repaired DNS" in item for item in messages)
