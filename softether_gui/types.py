from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CommandResult:
    returncode: int
    output: str
    stderr: str = ""
    commands: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and "Error occurred." not in self.output


@dataclass(slots=True)
class VpnAccount:
    name: str
    status: str = "Unknown"
    server: str = ""
    hub: str = ""
    nic: str = ""

    @property
    def is_connected(self) -> bool:
        return self.status.lower() == "connected"

    @property
    def is_active(self) -> bool:
        return self.status.lower() in {"connected", "connecting", "retrying"}


@dataclass(slots=True)
class VirtualNic:
    name: str
    status: str = "Unknown"
    mac: str = ""
    version: str = ""


@dataclass(slots=True)
class AccountProfile:
    name: str = ""
    server: str = ""
    port: int = 443
    hub: str = "DEFAULT"
    username: str = ""
    nic: str = ""
    auth_type: str = "standard"  # standard, radius, anonymous, certificate
    password: str = ""
    certificate_path: str = ""
    private_key_path: str = ""
    proxy_type: str = "direct"  # direct, http, socks
    proxy_server: str = ""
    proxy_port: int = 8080
    proxy_username: str = ""
    proxy_password: str = ""
    change_proxy_settings: bool = False
    verify_server_certificate: bool = False
    encrypt: bool = True
    compress: bool = False
    max_tcp: int = 1
    tcp_interval: int = 1
    tcp_ttl: int = 0
    half_duplex: bool = False
    bridge_mode: bool = False
    monitor_mode: bool = False
    no_route_tracking: bool = False
    disable_qos: bool = False
    disable_udp_acceleration: bool = False
    retry_count: int = 999
    retry_interval: int = 15
    change_retry_settings: bool = False
    startup: bool = False
    change_startup_setting: bool = False
    dhcp_after_connect: bool = True

    @property
    def interface_name(self) -> str:
        return f"vpn_{self.nic}" if self.nic else ""


@dataclass(slots=True)
class AppConfig:
    softether_dir: str = ""
    vpncmd_path: str = ""
    vpnclient_path: str = ""
    management_host: str = "localhost"
    close_to_tray: bool = True
    start_minimized: bool = False
    auto_start_client: bool = True
    default_dhcp: bool = True
    account_options: dict[str, dict[str, Any]] = field(default_factory=dict)

    def dhcp_for(self, account_name: str) -> bool:
        return bool(self.account_options.get(account_name, {}).get("dhcp", self.default_dhcp))

    def set_dhcp_for(self, account_name: str, enabled: bool) -> None:
        options = self.account_options.setdefault(account_name, {})
        options["dhcp"] = bool(enabled)

    def rename_account_options(self, old_name: str, new_name: str) -> None:
        if old_name == new_name:
            return
        if old_name in self.account_options:
            self.account_options[new_name] = self.account_options.pop(old_name)
