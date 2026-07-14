from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import threading
import time

from .config import repair_runtime_config, save_config
from .parser import (
    error_message,
    parse_account_list,
    parse_account_profile,
    parse_nic_list,
    parse_status_pairs,
)
from .types import AccountProfile, AppConfig, CommandResult, VirtualNic, VpnAccount


class VpncmdError(RuntimeError):
    def __init__(self, message: str, result: CommandResult | None = None):
        super().__init__(message)
        self.result = result


class ClientPasswordRequired(VpncmdError):
    pass


def quote(value: str) -> str:
    if value is None:
        return '""'
    value = str(value)
    if "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("SoftEther values may not contain newlines or NUL characters.")
    if '"' in value:
        raise ValueError('Double quotes are not supported in SoftEther command values.')
    return '"' + value + '"'


def parameter(name: str, value: str | int) -> str:
    return f"/{name}:{quote(str(value))}"


class SoftEtherBackend:
    def __init__(self, config: AppConfig):
        self.config = config
        self.management_password: str = ""
        self._helper_process: subprocess.Popen[str] | None = None
        self._helper_lock = threading.RLock()
        self._helper_request_id = 0

    @property
    def vpncmd_path(self) -> str:
        return self.config.vpncmd_path

    @property
    def softether_dir(self) -> str:
        return os.path.abspath(os.path.expanduser(self.config.softether_dir)) if self.config.softether_dir else ""

    @property
    def vpncmd_launch_path(self) -> str:
        """Return the relative executable used after changing into softether_dir.

        SoftEther's Linux binaries historically expect hamcore.se2 beside the
        executable and some builds behave best when invoked exactly as users do
        manually: `cd /path/to/vpnclient && ./vpncmd ...`.
        """
        return "./vpncmd"

    def validate(self) -> None:
        # Self-heal stale paths, but do not require the desktop user to read or
        # execute the root-owned SoftEther files.  The PolicyKit helper performs
        # the authoritative checks after it has administrator privileges.
        if repair_runtime_config(self.config):
            try:
                save_config(self.config)
            except OSError:
                pass

        directory = self.softether_dir
        path = os.path.abspath(os.path.expanduser(self.vpncmd_path)) if self.vpncmd_path else ""
        if not directory:
            raise VpncmdError(
                "The SoftEther program directory is not configured. Open Edit > Preferences and "
                "select the folder containing vpncmd, vpnclient, and hamcore.se2."
            )
        if not path:
            raise VpncmdError(
                "vpncmd is not configured. Open Edit > Preferences and select the vpncmd executable."
            )
        if os.path.basename(path) != "vpncmd":
            raise VpncmdError(f'The configured vpncmd must be named "vpncmd": {path}')
        expected = os.path.join(directory, "vpncmd")
        if os.path.normpath(path) != os.path.normpath(expected):
            raise VpncmdError(
                f'The configured vpncmd "{path}" is not inside the configured SoftEther directory "{directory}".'
            )

    def set_management_password(self, password: str) -> None:
        self.management_password = password

    def authorize(self, timeout: int = 15) -> None:
        """Open and verify the persistent PolicyKit helper session.

        This is called before the main window is created, so the native
        administrator-password dialog appears first rather than popping up
        over an already visible, empty manager window.
        """
        result = self._privileged_request({"action": "authorize"}, timeout, ("authorize",))
        if not result.ok:
            raise VpncmdError(result.stderr or result.output or "Administrator authorization failed.", result)

    def run(self, commands: list[str], timeout: int = 45, secrets: tuple[str, ...] = ()) -> CommandResult:
        self.validate()
        if not commands:
            raise ValueError("At least one command is required.")
        if self.management_password:
            return self._run_interactive(commands, timeout, secrets)
        result = self._run_batch(commands, timeout, secrets)
        lower = (result.output + result.stderr).casefold()
        password_prompt = "password:" in lower and "command completed successfully" not in lower
        if password_prompt or (not result.ok and "password" in lower and ("vpn client" in lower or "authentication" in lower)):
            raise ClientPasswordRequired("The local VPN Client service requires its management password.", result)
        if not result.ok:
            raise VpncmdError(error_message(result.output + "\n" + result.stderr), result)
        return result

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["LANG"] = "C.UTF-8"
        env["LC_ALL"] = "C.UTF-8"
        return env

    def _helper_path(self) -> str:
        helper = shutil.which("softether-gui-helper") or "/usr/libexec/softether-gui-helper"
        if not os.path.isfile(helper):
            raise VpncmdError("The PolicyKit helper is not installed. Run scripts/install.sh again.")
        return helper

    def _start_helper_session(self) -> subprocess.Popen[str]:
        process = self._helper_process
        if process is not None and process.poll() is None:
            return process

        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise VpncmdError("pkexec is not installed. Install the pkexec package (polkitd is also required).")

        # pkexec asks for the administrator password through the desktop's
        # PolicyKit agent.  The helper then remains alive for this GUI session,
        # so subsequent commands do not repeatedly display password dialogs.
        process = subprocess.Popen(
            [pkexec, self._helper_path(), "session"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self._environment(),
        )
        self._helper_process = process
        return process

    def _discard_helper_session(self) -> None:
        process = self._helper_process
        self._helper_process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def close(self) -> None:
        with self._helper_lock:
            process = self._helper_process
            if process is None:
                return
            if process.poll() is None and process.stdin and process.stdout:
                try:
                    self._helper_request_id += 1
                    process.stdin.write(json.dumps({"id": self._helper_request_id, "action": "quit"}) + "\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            self._discard_helper_session()

    def _privileged_request(
        self,
        payload: dict[str, object],
        timeout: int,
        commands: tuple[str, ...] = (),
    ) -> CommandResult:
        with self._helper_lock:
            process = self._start_helper_session()
            if process.stdin is None or process.stdout is None:
                self._discard_helper_session()
                raise VpncmdError("The PolicyKit helper could not open its communication pipes.")

            self._helper_request_id += 1
            request_id = self._helper_request_id
            request = dict(payload)
            request["id"] = request_id
            request["timeout"] = timeout
            try:
                process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._discard_helper_session()
                raise VpncmdError(
                    "Administrator authorization was cancelled or the privileged helper stopped."
                ) from exc

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                ready = selector.select(timeout + 120)
            finally:
                selector.close()
            if not ready:
                self._discard_helper_session()
                raise VpncmdError("Timed out waiting for administrator authorization or the SoftEther command.")

            line = process.stdout.readline()
            if not line:
                stderr = ""
                if process.poll() is not None and process.stderr is not None:
                    stderr = process.stderr.read().strip()
                self._discard_helper_session()
                detail = stderr or "The administrator request was cancelled or denied."
                raise VpncmdError(detail)

            try:
                reply = json.loads(line)
            except json.JSONDecodeError as exc:
                self._discard_helper_session()
                raise VpncmdError(f"The privileged helper returned an invalid response: {line.strip()}") from exc
            if not isinstance(reply, dict) or reply.get("id") != request_id:
                self._discard_helper_session()
                raise VpncmdError("The privileged helper returned a mismatched response.")

            return CommandResult(
                int(reply.get("returncode", 1)),
                str(reply.get("output", "")),
                str(reply.get("stderr", "")),
                commands,
            )

    def _vpncmd_payload(self) -> dict[str, object]:
        return {
            "softether_dir": self.softether_dir,
            "vpncmd_path": os.path.abspath(os.path.expanduser(self.vpncmd_path)),
            "host": self.config.management_host or "localhost",
        }

    def _run_batch(self, commands: list[str], timeout: int, secrets: tuple[str, ...]) -> CommandResult:
        payload = self._vpncmd_payload()
        payload.update({"action": "vpncmd-batch", "commands": commands})
        result = self._privileged_request(payload, timeout, tuple(commands))
        output, stderr = self._redact(result.output, result.stderr, secrets)
        return CommandResult(result.returncode, output, stderr, result.commands)

    def _run_interactive(self, commands: list[str], timeout: int, secrets: tuple[str, ...]) -> CommandResult:
        payload = self._vpncmd_payload()
        payload.update(
            {
                "action": "vpncmd-interactive",
                "commands": commands,
                "management_password": self.management_password,
            }
        )
        result = self._privileged_request(payload, timeout, tuple(commands))
        output, stderr = self._redact(
            result.output, result.stderr, secrets + (self.management_password,)
        )
        result = CommandResult(result.returncode, output, stderr, result.commands)
        if not result.ok:
            combined = (output + "\n" + stderr).casefold()
            if "password" in combined or "authentication" in combined:
                self.management_password = ""
                raise ClientPasswordRequired("The VPN Client management password was rejected.", result)
            raise VpncmdError(error_message(output + "\n" + stderr), result)
        return result

    @staticmethod
    def _redact(output: str, stderr: str, secrets: tuple[str, ...]) -> tuple[str, str]:
        for secret in secrets:
            if secret:
                output = output.replace(secret, "<redacted>")
                stderr = stderr.replace(secret, "<redacted>")
        return output, stderr

    def list_accounts(self) -> list[VpnAccount]:
        # Always query the running SoftEther client. The GUI does not maintain
        # its own shadow list of accounts, so connections created with vpncmd or
        # another manager appear automatically.
        return parse_account_list(self.run(["AccountList"]).output)

    def list_nics(self) -> list[VirtualNic]:
        # As with accounts, virtual adapters are discovered from SoftEther on
        # every refresh rather than from local GUI configuration.
        return parse_nic_list(self.run(["NicList"]).output)

    def load_state(self) -> tuple[list[VpnAccount], list[VirtualNic]]:
        """Load every existing connection setting and virtual adapter."""
        return self.list_accounts(), self.list_nics()

    @staticmethod
    def _local_client_unavailable(exc: VpncmdError) -> bool:
        """Return True when vpncmd could not reach the local Client service.

        ``vpnclient status`` is not implemented or worded consistently across
        SoftEther Linux builds.  Refresh therefore treats AccountList/NicList as
        the authoritative service probe and only converts their well-known local
        management connection failure into the normal "service stopped" state.
        """
        pieces = [str(exc)]
        if exc.result is not None:
            pieces.extend((exc.result.output, exc.result.stderr))
        text = "\n".join(piece for piece in pieces if piece).casefold()
        tokens = (
            "connection to server failed",
            "failed to connect to the server",
            "cannot connect to the server",
            "could not connect to the server",
            "connection refused",
            "vpn client service is not running",
            "vpn client service is stopped",
            "softether error 1",
            "error code: 1",
        )
        return any(token in text for token in tokens)

    def load_state_if_running(self) -> tuple[list[VpnAccount], list[VirtualNic]] | None:
        """Load live SoftEther state, or return ``None`` when it is unreachable.

        Do not preflight with ``vpnclient status``.  Some Linux SoftEther builds
        accept start/stop but do not provide a dependable status operation, which
        caused Refresh to clear a healthy, connected account list.  The actual
        vpncmd list request is the authoritative check.
        """
        try:
            return self.load_state()
        except ClientPasswordRequired:
            raise
        except VpncmdError as exc:
            if self._local_client_unavailable(exc):
                return None
            raise

    def load_stable_state_if_running(
        self,
        expected_accounts: frozenset[str] = frozenset(),
        expected_nics: frozenset[str] = frozenset(),
    ) -> tuple[list[VpnAccount], list[VirtualNic]] | None:
        """Return a stable live snapshot, or ``None`` when the service is off.

        AccountList/NicList are both the data source and service-health check.
        This avoids the unreliable Linux ``vpnclient status`` command while still
        protecting the display from transient empty list responses.
        """
        try:
            # Probe with the same authoritative command used to populate the UI.
            # This makes a deliberately stopped service return immediately,
            # without relying on the inconsistent ``vpnclient status`` command.
            self.load_state()
        except ClientPasswordRequired:
            raise
        except VpncmdError as exc:
            if self._local_client_unavailable(exc):
                return None
            raise

        try:
            return self.wait_for_state(
                seconds=4.0,
                poll_interval=0.4,
                expected_accounts=expected_accounts,
                expected_nics=expected_nics,
                settle_seconds=4.0,
            )
        except ClientPasswordRequired:
            raise
        except VpncmdError as exc:
            if self._local_client_unavailable(exc):
                return None
            raise

    def wait_for_state(
        self,
        seconds: float = 20,
        poll_interval: float = 0.5,
        expected_accounts: frozenset[str] = frozenset(),
        expected_nics: frozenset[str] = frozenset(),
        settle_seconds: float = 4.0,
    ) -> tuple[list[VpnAccount], list[VirtualNic]]:
        """Wait for vpncmd and SoftEther's saved configuration to be ready.

        The local management listener may begin accepting commands before the
        service has finished loading ``vpn_client.config``.  During that short
        window AccountList and NicList can both succeed while returning empty or
        incomplete lists.  Do not treat that first successful snapshot as final.

        When the GUI knows which settings existed before the service was stopped,
        wait briefly for those names to reappear.  Otherwise require two matching
        snapshots.  This is startup settling after a human action, not periodic
        monitoring.
        """
        started = time.monotonic()
        deadline = started + seconds
        last_error: VpncmdError | None = None
        last_state: tuple[list[VpnAccount], list[VirtualNic]] | None = None
        last_signature: tuple[tuple[tuple[str, str, str, str, str], ...], tuple[tuple[str, str, str, str], ...]] | None = None
        stable_snapshots = 0

        while True:
            now = time.monotonic()
            try:
                state = self.load_state()
                last_state = state
                accounts, nics = state
                account_names = frozenset(item.name for item in accounts)
                nic_names = frozenset(item.name for item in nics)
                signature = (
                    tuple((item.name, item.status, item.server, item.hub, item.nic) for item in accounts),
                    tuple((item.name, item.status, item.mac, item.version) for item in nics),
                )
                if signature == last_signature:
                    stable_snapshots += 1
                else:
                    last_signature = signature
                    stable_snapshots = 1

                expected_visible = (
                    expected_accounts.issubset(account_names)
                    and expected_nics.issubset(nic_names)
                )
                has_expected_names = bool(expected_accounts or expected_nics)

                if expected_visible and stable_snapshots >= 2:
                    return state
                if not has_expected_names and stable_snapshots >= 2:
                    return state
                # If settings were changed externally while the service was off,
                # do not wait the full command timeout for names that no longer
                # exist.  Four seconds still gives normal SoftEther startup ample
                # time to restore the prior list.
                if now - started >= settle_seconds and stable_snapshots >= 2:
                    return state
            except ClientPasswordRequired:
                raise
            except VpncmdError as exc:
                last_error = exc

            if now >= deadline:
                break
            time.sleep(max(0.0, poll_interval))

        if last_state is not None:
            return last_state

        detail = ""
        if last_error:
            detail = f" Last error: {last_error}"
        raise VpncmdError(
            "The VPN Client management interface did not become ready "
            f"within {seconds:g} seconds.{detail}",
            last_error.result if last_error else None,
        )

    def client_start_and_load_state(
        self,
        expected_accounts: frozenset[str] = frozenset(),
        expected_nics: frozenset[str] = frozenset(),
    ) -> tuple[list[VpnAccount], list[VirtualNic]]:
        """Start vpnclient, then wait for saved accounts and adapters to load."""
        self.client_start()
        return self.wait_for_state(
            expected_accounts=expected_accounts,
            expected_nics=expected_nics,
        )

    def get_profile(self, account_name: str) -> AccountProfile:
        result = self.run([f"AccountGet {quote(account_name)}"])
        return parse_account_profile(account_name, result.output, self.config.dhcp_for(account_name))

    def get_status(self, account_name: str) -> list[tuple[str, str]]:
        result = self.run([f"AccountStatusGet {quote(account_name)}"])
        return parse_status_pairs(result.output)

    def connect(self, account: VpnAccount) -> None:
        self.run([f"AccountConnect {quote(account.name)}"])
        if self.config.dhcp_for(account.name):
            self._wait_until_connected(account.name)
            self.dhcp_start(f"vpn_{account.nic}")

    def disconnect(self, account: VpnAccount) -> None:
        # Disconnect SoftEther first, then remove the Linux interface's DHCP,
        # routes and DNS. This mirrors the proven manual script sequence and
        # prevents a still-active account from immediately restoring VPN state.
        self.run([f"AccountDisconnect {quote(account.name)}"])
        if self.config.dhcp_for(account.name) and account.nic:
            self.dhcp_stop(f"vpn_{account.nic}", tolerate_errors=False)

    def _wait_until_connected(self, account_name: str, seconds: int = 25) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for account in self.list_accounts():
                if account.name == account_name and account.is_connected:
                    return
            time.sleep(1)
        raise VpncmdError(
            f'Connection "{account_name}" did not reach Connected state before the DHCP timeout.'
        )

    def create_account(self, profile: AccountProfile) -> None:
        commands, secrets = self._profile_commands(profile, creating=True)
        self.run(commands, timeout=60, secrets=secrets)
        self.config.set_dhcp_for(profile.name, profile.dhcp_after_connect)
        save_config(self.config)

    def update_account(self, original_name: str, profile: AccountProfile) -> None:
        commands, secrets = self._profile_commands(profile, creating=False, original_name=original_name)
        self.run(commands, timeout=60, secrets=secrets)
        self.config.rename_account_options(original_name, profile.name)
        self.config.set_dhcp_for(profile.name, profile.dhcp_after_connect)
        save_config(self.config)

    def _profile_commands(
        self, profile: AccountProfile, creating: bool, original_name: str | None = None
    ) -> tuple[list[str], tuple[str, ...]]:
        current_name = original_name or profile.name
        server = f"{profile.server}:{profile.port}"
        commands: list[str] = []
        secrets: list[str] = []
        if creating:
            commands.append(
                " ".join(
                    (
                        f"AccountCreate {quote(profile.name)}",
                        parameter("SERVER", server),
                        parameter("HUB", profile.hub),
                        parameter("USERNAME", profile.username),
                        parameter("NICNAME", profile.nic),
                    )
                )
            )
            current_name = profile.name
        else:
            commands.extend(
                (
                    f"AccountSet {quote(current_name)} {parameter('SERVER', server)} {parameter('HUB', profile.hub)}",
                    f"AccountUsernameSet {quote(current_name)} {parameter('USERNAME', profile.username)}",
                    f"AccountNicSet {quote(current_name)} {parameter('NICNAME', profile.nic)}",
                )
            )

        if profile.auth_type == "anonymous":
            commands.append(f"AccountAnonymousSet {quote(current_name)}")
        elif profile.auth_type == "certificate":
            if profile.certificate_path and profile.private_key_path:
                commands.append(
                    f"AccountCertSet {quote(current_name)} "
                    f"{parameter('LOADCERT', profile.certificate_path)} "
                    f"{parameter('LOADKEY', profile.private_key_path)}"
                )
            elif creating:
                raise ValueError("Certificate authentication requires both certificate and private key files.")
        elif profile.password:
            auth_kind = "radius" if profile.auth_type == "radius" else "standard"
            commands.append(
                f"AccountPasswordSet {quote(current_name)} "
                f"{parameter('PASSWORD', profile.password)} /TYPE:{auth_kind}"
            )
            secrets.append(profile.password)
        elif creating:
            raise ValueError("Password authentication requires a password when creating an account.")

        if creating or profile.change_proxy_settings:
            if profile.proxy_type == "http":
                proxy = f"{profile.proxy_server}:{profile.proxy_port}"
                command = f"AccountProxyHttp {quote(current_name)} {parameter('SERVER', proxy)}"
                if profile.proxy_username:
                    command += f" {parameter('USERNAME', profile.proxy_username)}"
                if profile.proxy_password:
                    command += f" {parameter('PASSWORD', profile.proxy_password)}"
                    secrets.append(profile.proxy_password)
                commands.append(command)
            elif profile.proxy_type == "socks":
                proxy = f"{profile.proxy_server}:{profile.proxy_port}"
                command = f"AccountProxySocks {quote(current_name)} {parameter('SERVER', proxy)}"
                if profile.proxy_username:
                    command += f" {parameter('USERNAME', profile.proxy_username)}"
                if profile.proxy_password:
                    command += f" {parameter('PASSWORD', profile.proxy_password)}"
                    secrets.append(profile.proxy_password)
                commands.append(command)
            else:
                commands.append(f"AccountProxyNone {quote(current_name)}")

        commands.append(
            f"AccountServerCert{'Enable' if profile.verify_server_certificate else 'Disable'} {quote(current_name)}"
        )
        commands.append(f"AccountEncrypt{'Enable' if profile.encrypt else 'Disable'} {quote(current_name)}")
        commands.append(f"AccountCompress{'Enable' if profile.compress else 'Disable'} {quote(current_name)}")
        detail = (
            f"AccountDetailSet {quote(current_name)} "
            f"/MAXTCP:{profile.max_tcp} /INTERVAL:{profile.tcp_interval} /TTL:{profile.tcp_ttl} "
            f"/HALF:{'yes' if profile.half_duplex else 'no'} "
            f"/BRIDGE:{'yes' if profile.bridge_mode else 'no'} "
            f"/MONITOR:{'yes' if profile.monitor_mode else 'no'} "
            f"/NOTRACK:{'yes' if profile.no_route_tracking else 'no'} "
            f"/NOQOS:{'yes' if profile.disable_qos else 'no'}"
        )
        # Newer builds accept /UDPACCEL; older builds reject it. Avoid changing it here.
        commands.append(detail)
        if creating or profile.change_retry_settings:
            commands.append(
                f"AccountRetrySet {quote(current_name)} /NUM:{profile.retry_count} /INTERVAL:{profile.retry_interval}"
            )
        if creating:
            if profile.startup:
                commands.append(f"AccountStartupSet {quote(current_name)}")
        elif profile.change_startup_setting:
            commands.append(
                f"AccountStartup{'Set' if profile.startup else 'Remove'} {quote(current_name)}"
            )
        if not creating and profile.name != current_name:
            commands.append(f"AccountRename {quote(current_name)} {parameter('NEW', profile.name)}")
        return commands, tuple(secrets)

    def delete_account(self, account_name: str) -> None:
        self.run([f"AccountDelete {quote(account_name)}"])
        self.config.account_options.pop(account_name, None)
        save_config(self.config)

    def export_account(self, account_name: str, path: str) -> None:
        self.run([f"AccountExport {quote(account_name)} {parameter('SAVEPATH', path)}"])

    def import_account(self, path: str) -> None:
        self.run([f"AccountImport {quote(path)}"])

    def create_nic(self, name: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,31}", name):
            raise ValueError("Adapter names may contain letters, numbers, underscore, dot and hyphen (31 max).")
        self.run([f"NicCreate {quote(name)}"])

    def delete_nic(self, name: str) -> None:
        self.run([f"NicDelete {quote(name)}"])

    def enable_nic(self, name: str, enabled: bool) -> None:
        self.run([f"Nic{'Enable' if enabled else 'Disable'} {quote(name)}"])

    def set_nic_mac(self, name: str, mac: str) -> None:
        normalized = mac.replace("-", ":").upper()
        if not re.fullmatch(r"[0-9A-F]{2}(?::[0-9A-F]{2}){5}", normalized):
            raise ValueError("Enter a MAC address such as 00:AC:01:23:45:67.")
        self.run([f"NicSetSetting {quote(name)} {parameter('MAC', normalized)}"])

    def helper(self, action: str, *arguments: str, privileged: bool = True, timeout: int = 40) -> CommandResult:
        del privileged  # Every helper operation uses the existing PolicyKit session.
        payload: dict[str, object] = {"action": action}
        if action in {"start-client", "stop-client", "status-client"}:
            payload.update(
                {
                    "softether_dir": self.softether_dir,
                    "vpnclient_path": os.path.abspath(os.path.expanduser(self.config.vpnclient_path)),
                }
            )
        elif action in {"dhcp-start", "dhcp-stop"}:
            if len(arguments) != 1:
                raise ValueError(f"{action} requires one interface name.")
            payload["interface"] = arguments[0]
        elif action in {"network-diagnostics", "network-repair"}:
            if arguments:
                raise ValueError(f"{action} does not accept arguments.")
        else:
            raise ValueError(f"Unknown helper action: {action}")

        result = self._privileged_request(payload, timeout, (action, *arguments))
        if not result.ok:
            raise VpncmdError(
                result.stderr.strip() or result.output.strip() or f"Helper action {action} failed.",
                result,
            )
        return result

    def _client_helper_args(self) -> list[str]:
        # Kept for compatibility with callers and tests; the persistent helper
        # reads these settings from the request rather than positional argv.
        return [self.config.vpnclient_path or "", self.config.softether_dir or ""]

    def client_start(self) -> None:
        self.helper("start-client")

    def client_stop(self) -> None:
        self.helper("stop-client")

    def client_status(self) -> str:
        """Return ``running`` or ``stopped`` for the local VPN Client service.

        Some SoftEther builds return a non-zero status code when the service is
        stopped even though that is a valid status response.  Inspect the text
        before deciding whether to raise an exception.
        """
        payload: dict[str, object] = {
            "action": "status-client",
            "softether_dir": self.softether_dir,
            "vpnclient_path": os.path.abspath(os.path.expanduser(self.config.vpnclient_path)),
        }
        result = self._privileged_request(payload, 20, ("status-client",))
        text = (result.output + "\n" + result.stderr).strip()
        lowered = text.casefold()

        stopped_tokens = (
            "not running",
            "is stopped",
            "has stopped",
            "service stopped",
        )
        if any(token in lowered for token in stopped_tokens):
            return "stopped"
        if "running" in lowered:
            return "running"
        if not result.ok:
            raise VpncmdError(text or "Unable to determine VPN Client service status.", result)

        # A successful but unusually worded response should remain visible to
        # diagnostics rather than being guessed incorrectly.
        return text or "unknown"

    def client_is_running(self) -> bool:
        return self.client_status() == "running"

    def dhcp_start(self, interface: str) -> None:
        self.helper("dhcp-start", interface)

    def dhcp_stop(self, interface: str, tolerate_errors: bool = False) -> None:
        try:
            self.helper("dhcp-stop", interface, timeout=60)
        except VpncmdError:
            if not tolerate_errors:
                raise

    def network_diagnostics(self) -> CommandResult:
        return self.helper("network-diagnostics", timeout=45)

    def repair_network(self) -> CommandResult:
        return self.helper("network-repair", timeout=60)

