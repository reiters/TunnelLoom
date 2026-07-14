from __future__ import annotations

import re
from collections.abc import Iterable

from .types import AccountProfile, VirtualNic, VpnAccount


_SEPARATOR = re.compile(r"^-{2,}\+[-+]+$")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def clean_output(text: str) -> str:
    return _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def parse_pairs(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in clean_output(text).splitlines():
        line = raw_line.strip()
        if not line or _SEPARATOR.match(line) or line.lower() == "item |value":
            continue
        if "|" not in raw_line:
            continue
        left, right = raw_line.split("|", 1)
        key = left.strip()
        value = right.strip()
        if key and key.lower() != "item":
            pairs.append((key, value))
    return pairs


def parse_records(text: str, starter_key: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    starter = starter_key.casefold()
    for key, value in parse_pairs(text):
        if key.casefold() == starter and current:
            records.append(current)
            current = {}
        current[key] = value
    if current:
        records.append(current)
    return records


def _pick(record: dict[str, str], names: Iterable[str], default: str = "") -> str:
    folded = {key.casefold(): value for key, value in record.items()}
    for name in names:
        if name.casefold() in folded:
            return folded[name.casefold()]
    return default


def _enabled(value: str, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().casefold() in {"enable", "enabled", "yes", "true", "on"}


def _integer(value: str, default: int = 0) -> int:
    if value.casefold() == "infinite":
        return 0
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else default


def parse_account_list(text: str) -> list[VpnAccount]:
    records = parse_records(text, "VPN Connection Setting Name")
    accounts: list[VpnAccount] = []
    for record in records:
        name = _pick(record, ("VPN Connection Setting Name", "Account Name"))
        if not name:
            continue
        accounts.append(
            VpnAccount(
                name=name,
                status=_pick(record, ("Status",), "Unknown"),
                server=_pick(record, ("VPN Server Hostname", "Destination VPN Server Host Name")),
                hub=_pick(record, ("Virtual Hub", "Destination VPN Server Virtual Hub Name")),
                nic=_pick(record, ("Virtual Network Adapter Name", "Device Name Used for Connection")),
            )
        )
    return accounts


def parse_nic_list(text: str) -> list[VirtualNic]:
    records = parse_records(text, "Virtual Network Adapter Name")
    nics: list[VirtualNic] = []
    for record in records:
        name = _pick(record, ("Virtual Network Adapter Name",))
        if not name:
            continue
        nics.append(
            VirtualNic(
                name=name,
                status=_pick(record, ("Status",), "Unknown"),
                mac=_pick(record, ("MAC Address",)),
                version=_pick(record, ("Version",)),
            )
        )
    return nics


def parse_account_profile(name: str, text: str, dhcp: bool = True) -> AccountProfile:
    record = dict(parse_pairs(text))
    host = _pick(record, ("Destination VPN Server Host Name",))
    port = _integer(_pick(record, ("Destination VPN Server Port Number",)), 443)
    auth = _pick(record, ("Authentication Type",)).casefold()
    if "anonymous" in auth:
        auth_type = "anonymous"
    elif "radius" in auth or "nt domain" in auth:
        auth_type = "radius"
    elif "certificate" in auth:
        auth_type = "certificate"
    else:
        auth_type = "standard"

    proxy_description = _pick(record, ("Proxy Server Type",)).casefold()
    if "http" in proxy_description:
        proxy_type = "http"
    elif "socks" in proxy_description:
        proxy_type = "socks"
    else:
        proxy_type = "direct"

    profile = AccountProfile(
        name=_pick(record, ("VPN Connection Setting Name",), name),
        server=host,
        port=port,
        hub=_pick(record, ("Destination VPN Server Virtual Hub Name",), "DEFAULT"),
        username=_pick(record, ("User Name",)),
        nic=_pick(record, ("Device Name Used for Connection",)),
        auth_type=auth_type,
        proxy_type=proxy_type,
        verify_server_certificate=_enabled(_pick(record, ("Verify Server Certificate",))),
        encrypt=_enabled(_pick(record, ("Encryption by SSL",)), True),
        compress=_enabled(_pick(record, ("Data Compression",))),
        max_tcp=_integer(_pick(record, ("Number of TCP Connections to Use in VPN Communication",)), 1),
        tcp_interval=_integer(_pick(record, ("Interval between Establishing Each TCP Connection",)), 1),
        tcp_ttl=_integer(_pick(record, ("Connection Life of Each TCP Connection",)), 0),
        half_duplex=_enabled(_pick(record, ("Use Half Duplex Mode",))),
        bridge_mode=_enabled(_pick(record, ("Connect by Bridge / Router Mode",))),
        monitor_mode=_enabled(_pick(record, ("Connect by Monitoring Mode",))),
        no_route_tracking=_enabled(_pick(record, ("No Adjustment for Routing Table",))),
        disable_qos=_enabled(_pick(record, ("Do not Use QoS Control Function",))),
        disable_udp_acceleration=_enabled(_pick(record, ("Disable UDP Acceleration",))),
        dhcp_after_connect=dhcp,
    )

    proxy_host = _pick(record, ("Proxy Server Host Name", "Proxy Server Hostname"))
    if proxy_host:
        if ":" in proxy_host:
            possible_host, possible_port = proxy_host.rsplit(":", 1)
            if possible_port.isdigit():
                profile.proxy_server = possible_host
                profile.proxy_port = int(possible_port)
            else:
                profile.proxy_server = proxy_host
        else:
            profile.proxy_server = proxy_host
    profile.proxy_username = _pick(record, ("Proxy Server User Name", "Proxy User Name"))
    return profile


def parse_status_pairs(text: str) -> list[tuple[str, str]]:
    return parse_pairs(text)


def error_message(text: str) -> str:
    cleaned = clean_output(text)
    match = re.search(r"Error occurred\.\s*\(Error code:\s*(\d+)\)\s*([^\n]*)", cleaned, re.I)
    if match:
        suffix = match.group(2).strip()
        return f"SoftEther error {match.group(1)}" + (f": {suffix}" if suffix else "")
    for line in cleaned.splitlines():
        if "error" in line.casefold():
            return line.strip()
    return "SoftEther command failed."
