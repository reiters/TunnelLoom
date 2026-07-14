from softether_gui.backend import SoftEtherBackend, quote
from softether_gui.types import AccountProfile, AppConfig, CommandResult


def backend():
    return SoftEtherBackend(AppConfig(vpncmd_path="/bin/true"))


def test_create_commands_include_auth_and_dhcp_is_not_a_vpncmd_command():
    profile = AccountProfile(
        name="workaccount", server="vpn.example.com", port=443, hub="DEFAULT",
        username="keith", nic="worknic", password="secret", startup=False
    )
    commands, secrets = backend()._profile_commands(profile, creating=True)
    joined = "\n".join(commands)
    assert "AccountCreate" in joined
    assert "AccountPasswordSet" in joined
    assert "AccountRetrySet" in joined
    assert "AccountStartupRemove" not in joined
    assert "dhcpcd" not in joined
    assert secrets == ("secret",)


def test_edit_does_not_overwrite_unknown_proxy_retry_or_startup_defaults():
    profile = AccountProfile(
        name="workaccount", server="vpn.example.com", hub="DEFAULT",
        username="keith", nic="worknic", auth_type="standard"
    )
    commands, _ = backend()._profile_commands(profile, creating=False, original_name="workaccount")
    joined = "\n".join(commands)
    assert "AccountProxy" not in joined
    assert "AccountRetrySet" not in joined
    assert "AccountStartup" not in joined


def test_quote_rejects_command_breakout_characters():
    try:
        quote('bad"value')
    except ValueError:
        pass
    else:
        raise AssertionError("quote should reject embedded double quotes")


def test_client_status_recognizes_stopped_even_with_nonzero_return(monkeypatch) -> None:
    from softether_gui.types import CommandResult

    backend = SoftEtherBackend(AppConfig(softether_dir="/tmp/vpnclient", vpnclient_path="/tmp/vpnclient/vpnclient"))
    monkeypatch.setattr(
        backend,
        "_privileged_request",
        lambda *_args, **_kwargs: CommandResult(1, "SoftEther VPN Client service is not running.", ""),
    )
    assert backend.client_status() == "stopped"
    assert backend.client_is_running() is False


def test_load_state_if_running_uses_vpncmd_even_if_status_is_unreliable(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    state = ([object()], [object()])
    monkeypatch.setattr(backend, "client_is_running", lambda: False)
    monkeypatch.setattr(backend, "load_state", lambda: state)
    assert backend.load_state_if_running() == state


def test_load_state_if_running_treats_local_connection_failure_as_stopped(monkeypatch) -> None:
    from softether_gui.backend import VpncmdError

    backend = SoftEtherBackend(AppConfig())
    failure = CommandResult(
        255,
        'SoftEther error 1: Connection to server failed.',
        '',
    )
    monkeypatch.setattr(
        backend,
        "load_state",
        lambda: (_ for _ in ()).throw(VpncmdError("Connection to server failed", failure)),
    )
    assert backend.load_state_if_running() is None


def test_load_state_if_running_does_not_hide_other_vpncmd_errors(monkeypatch) -> None:
    import pytest
    from softether_gui.backend import VpncmdError

    backend = SoftEtherBackend(AppConfig())
    error = VpncmdError("Unexpected parser or authentication failure")
    monkeypatch.setattr(backend, "load_state", lambda: (_ for _ in ()).throw(error))
    with pytest.raises(VpncmdError):
        backend.load_state_if_running()


def test_stable_refresh_waits_for_expected_visible_state_without_status_preflight(monkeypatch) -> None:
    backend = SoftEtherBackend(AppConfig())
    expected = ([object()], [object()])
    captured = {}
    calls = []
    monkeypatch.setattr(backend, "client_is_running", lambda: False)
    monkeypatch.setattr(backend, "load_state", lambda: calls.append("AccountList/NicList") or expected)

    def fake_wait_for_state(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(backend, "wait_for_state", fake_wait_for_state)
    accounts = frozenset({"workaccount"})
    nics = frozenset({"worknic"})
    assert backend.load_stable_state_if_running(accounts, nics) == expected
    assert calls == ["AccountList/NicList"]
    assert captured["expected_accounts"] == accounts
    assert captured["expected_nics"] == nics
    assert captured["settle_seconds"] == 4.0


def test_interface_ipv4_address_reads_first_global_address(monkeypatch) -> None:
    import subprocess

    backend = SoftEtherBackend(AppConfig())

    class Completed:
        returncode = 0
        stdout = "12: vpn_worknic    inet 172.30.14.20/20 brd 172.30.15.255 scope global vpn_worknic\\n"

    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("softether_gui.backend.shutil.which", lambda name: "/usr/sbin/ip" if name == "ip" else None)
    monkeypatch.setattr("softether_gui.backend.subprocess.run", fake_run)

    assert backend.interface_ipv4_address("vpn_worknic") == "172.30.14.20"
    assert captured["argv"] == [
        "/usr/sbin/ip",
        "-4",
        "-o",
        "address",
        "show",
        "dev",
        "vpn_worknic",
        "scope",
        "global",
    ]
    assert captured["kwargs"]["check"] is False


def test_list_accounts_adds_ip_only_to_connected_accounts(monkeypatch) -> None:
    output = """
VPN Connection Setting Name |workaccount
Status                      |Connected
VPN Server Hostname         |vpn.example.com:443 (Direct TCP/IP Connection)
Virtual Hub                 |DEFAULT
Virtual Network Adapter Name|worknic
----------------------------+------------------------------------------------------------
VPN Connection Setting Name |backup
Status                      |Offline
VPN Server Hostname         |backup.example.com:443 (Direct TCP/IP Connection)
Virtual Hub                 |DEFAULT
Virtual Network Adapter Name|backupnic
The command completed successfully.
"""
    backend = SoftEtherBackend(AppConfig())
    monkeypatch.setattr(backend, "run", lambda _commands: CommandResult(0, output, ""))
    calls = []
    monkeypatch.setattr(
        backend,
        "interface_ipv4_address",
        lambda interface: calls.append(interface) or "172.30.14.20",
    )

    accounts = backend.list_accounts()

    assert accounts[0].vpn_ip == "172.30.14.20"
    assert accounts[1].vpn_ip == ""
    assert calls == ["vpn_worknic"]
