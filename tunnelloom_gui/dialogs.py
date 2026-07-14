from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .types import AccountProfile, AppConfig, VirtualNic


class AccountDialog(QDialog):
    def __init__(
        self,
        nics: list[VirtualNic],
        profile: AccountProfile | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._creating = profile is None
        self._original_auth_type = profile.auth_type if profile else ""
        self.setWindowTitle("New VPN Connection Setting" if self._creating else "VPN Connection Properties")
        self.resize(620, 560)
        self.tabs = QTabWidget()
        self.general_tab = QWidget()
        self.proxy_tab = QWidget()
        self.advanced_tab = QWidget()
        self.network_tab = QWidget()
        self.tabs.addTab(self.general_tab, "General")
        self.tabs.addTab(self.proxy_tab, "Proxy")
        self.tabs.addTab(self.advanced_tab, "Advanced")
        self.tabs.addTab(self.network_tab, "Linux Network")

        self.name = QLineEdit()
        self.server = QLineEdit()
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(443)
        self.hub = QLineEdit("DEFAULT")
        self.username = QLineEdit()
        self.nic = QComboBox()
        self.nic.setEditable(True)
        self.nic.addItems([item.name for item in nics])
        self.auth_type = QComboBox()
        self.auth_type.addItem("Standard Password Authentication", "standard")
        self.auth_type.addItem("RADIUS / NT Domain Authentication", "radius")
        self.auth_type.addItem("Anonymous Authentication", "anonymous")
        self.auth_type.addItem("Client Certificate Authentication", "certificate")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Required for new account; blank keeps current password")
        self.cert_path = QLineEdit()
        self.key_path = QLineEdit()
        cert_button = QPushButton("Browse…")
        key_button = QPushButton("Browse…")
        cert_button.clicked.connect(lambda: self._browse(self.cert_path, "Certificate files (*.cer *.crt *.pem);;All files (*)"))
        key_button.clicked.connect(lambda: self._browse(self.key_path, "Private keys (*.key *.pem);;All files (*)"))

        general = QGridLayout(self.general_tab)
        general.addWidget(QLabel("Connection setting name:"), 0, 0)
        general.addWidget(self.name, 0, 1, 1, 2)
        general.addWidget(QLabel("VPN server hostname:"), 1, 0)
        general.addWidget(self.server, 1, 1)
        general.addWidget(QLabel("Port:"), 1, 2)
        general.addWidget(self.port, 1, 3)
        general.addWidget(QLabel("Virtual Hub:"), 2, 0)
        general.addWidget(self.hub, 2, 1, 1, 3)
        general.addWidget(QLabel("Virtual network adapter:"), 3, 0)
        general.addWidget(self.nic, 3, 1, 1, 3)

        auth_box = QGroupBox("User Authentication")
        auth_layout = QGridLayout(auth_box)
        auth_layout.addWidget(QLabel("Authentication type:"), 0, 0)
        auth_layout.addWidget(self.auth_type, 0, 1, 1, 2)
        auth_layout.addWidget(QLabel("User name:"), 1, 0)
        auth_layout.addWidget(self.username, 1, 1, 1, 2)
        auth_layout.addWidget(QLabel("Password:"), 2, 0)
        auth_layout.addWidget(self.password, 2, 1, 1, 2)
        auth_layout.addWidget(QLabel("Client certificate:"), 3, 0)
        auth_layout.addWidget(self.cert_path, 3, 1)
        auth_layout.addWidget(cert_button, 3, 2)
        auth_layout.addWidget(QLabel("Private key:"), 4, 0)
        auth_layout.addWidget(self.key_path, 4, 1)
        auth_layout.addWidget(key_button, 4, 2)
        general.addWidget(auth_box, 4, 0, 1, 4)
        general.setRowStretch(5, 1)

        self.proxy_type = QComboBox()
        self.proxy_type.addItem("Direct TCP/IP connection", "direct")
        self.proxy_type.addItem("HTTP proxy server", "http")
        self.proxy_type.addItem("SOCKS 4 proxy server", "socks")
        self.proxy_server = QLineEdit()
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(8080)
        self.proxy_username = QLineEdit()
        self.proxy_password = QLineEdit()
        self.proxy_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.change_proxy = QCheckBox("Apply proxy settings when saving")
        self.change_proxy.setChecked(self._creating)
        proxy_form = QFormLayout(self.proxy_tab)
        proxy_form.addRow(self.change_proxy)
        proxy_form.addRow("Connection method:", self.proxy_type)
        host_row = QHBoxLayout()
        host_row.addWidget(self.proxy_server, 1)
        host_row.addWidget(QLabel("Port:"))
        host_row.addWidget(self.proxy_port)
        proxy_form.addRow("Proxy server:", host_row)
        proxy_form.addRow("Proxy user name:", self.proxy_username)
        proxy_form.addRow("Proxy password:", self.proxy_password)
        proxy_form.addRow(QLabel("SOCKS mode uses SOCKS version 4, matching SoftEther's client command."))

        self.encrypt = QCheckBox("Encrypt VPN session with SSL")
        self.encrypt.setChecked(True)
        self.compress = QCheckBox("Use data compression")
        self.verify_cert = QCheckBox("Verify VPN server certificate")
        self.max_tcp = QSpinBox()
        self.max_tcp.setRange(1, 32)
        self.max_tcp.setValue(1)
        self.tcp_interval = QSpinBox()
        self.tcp_interval.setRange(0, 60)
        self.tcp_interval.setValue(1)
        self.tcp_ttl = QSpinBox()
        self.tcp_ttl.setRange(0, 86400)
        self.tcp_ttl.setSpecialValueText("Infinite")
        self.half_duplex = QCheckBox("Use half-duplex mode")
        self.bridge_mode = QCheckBox("Bridge / Router mode")
        self.monitor_mode = QCheckBox("Monitoring mode")
        self.no_route = QCheckBox("Do not adjust routing table")
        self.disable_qos = QCheckBox("Disable VoIP / QoS functions")
        self.retry_count = QSpinBox()
        self.retry_count.setRange(0, 999)
        self.retry_count.setValue(999)
        self.retry_count.setSpecialValueText("No retries")
        self.retry_interval = QSpinBox()
        self.retry_interval.setRange(1, 3600)
        self.retry_interval.setValue(15)
        self.change_retry = QCheckBox("Apply retry settings when saving")
        self.change_retry.setChecked(self._creating)
        self.startup = QCheckBox("Set as startup connection")
        self.change_startup = QCheckBox("Apply startup setting when saving")
        self.change_startup.setChecked(self._creating)

        advanced_layout = QVBoxLayout(self.advanced_tab)
        crypto_box = QGroupBox("Encryption and Compression")
        crypto_layout = QVBoxLayout(crypto_box)
        crypto_layout.addWidget(self.encrypt)
        crypto_layout.addWidget(self.compress)
        crypto_layout.addWidget(self.verify_cert)
        advanced_layout.addWidget(crypto_box)
        transport_box = QGroupBox("VPN Communication")
        transport = QFormLayout(transport_box)
        transport.addRow("Number of TCP connections:", self.max_tcp)
        transport.addRow("Additional TCP connection interval (seconds):", self.tcp_interval)
        transport.addRow("TCP connection lifetime (seconds):", self.tcp_ttl)
        transport.addRow(self.half_duplex)
        advanced_layout.addWidget(transport_box)
        mode_box = QGroupBox("Connection Mode")
        mode_layout = QVBoxLayout(mode_box)
        mode_layout.addWidget(self.bridge_mode)
        mode_layout.addWidget(self.monitor_mode)
        mode_layout.addWidget(self.no_route)
        mode_layout.addWidget(self.disable_qos)
        advanced_layout.addWidget(mode_box)
        retry_box = QGroupBox("Automatic Reconnection")
        retry_layout = QFormLayout(retry_box)
        retry_layout.addRow(self.change_retry)
        retry_layout.addRow("Number of retries (999 = unlimited):", self.retry_count)
        retry_layout.addRow("Retry interval (seconds):", self.retry_interval)
        retry_layout.addRow(self.change_startup)
        retry_layout.addRow(self.startup)
        advanced_layout.addWidget(retry_box)
        advanced_layout.addStretch(1)

        self.dhcp = QCheckBox("Request an IPv4 address with dhcpcd after connection")
        self.dhcp.setChecked(True)
        network_layout = QVBoxLayout(self.network_tab)
        network_layout.addWidget(self.dhcp)
        network_layout.addWidget(
            QLabel(
                "On Linux, SoftEther creates an Ethernet interface named vpn_<adapter>. "
                "The Windows client assigns IP settings through the operating system; this option performs "
                "the equivalent DHCP step automatically using the installed privileged helper."
            )
        )
        network_layout.addStretch(1)

        self.auth_type.currentIndexChanged.connect(self._update_enabled)
        self.proxy_type.currentIndexChanged.connect(self._update_enabled)
        self.change_proxy.toggled.connect(self._update_enabled)
        self.change_retry.toggled.connect(self._update_enabled)
        self.change_startup.toggled.connect(self._update_enabled)
        self._update_enabled()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

        if profile:
            self.set_profile(profile)

    def _browse(self, target: QLineEdit, file_filter: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select file", target.text(), file_filter)
        if path:
            target.setText(path)

    def _update_enabled(self) -> None:
        auth = self.auth_type.currentData()
        password_enabled = auth in {"standard", "radius"}
        cert_enabled = auth == "certificate"
        self.password.setEnabled(password_enabled)
        self.cert_path.setEnabled(cert_enabled)
        self.key_path.setEnabled(cert_enabled)
        proxy_apply = self._creating or self.change_proxy.isChecked()
        self.proxy_type.setEnabled(proxy_apply)
        proxy = proxy_apply and self.proxy_type.currentData() != "direct"
        for control in (self.proxy_server, self.proxy_port, self.proxy_username, self.proxy_password):
            control.setEnabled(proxy)
        retry_apply = self._creating or self.change_retry.isChecked()
        self.retry_count.setEnabled(retry_apply)
        self.retry_interval.setEnabled(retry_apply)
        startup_apply = self._creating or self.change_startup.isChecked()
        self.startup.setEnabled(startup_apply)

    def _accept(self) -> None:
        required = {
            "Connection setting name": self.name.text().strip(),
            "VPN server hostname": self.server.text().strip(),
            "Virtual Hub": self.hub.text().strip(),
            "Virtual network adapter": self.nic.currentText().strip(),
        }
        for label, value in required.items():
            if not value:
                QMessageBox.warning(self, "Missing information", f"{label} is required.")
                return
        auth_changed = not self._creating and self.auth_type.currentData() != self._original_auth_type
        if (self._creating or auth_changed) and self.auth_type.currentData() in {"standard", "radius"} and not self.password.text():
            QMessageBox.warning(self, "Missing password", "Enter a password when creating or changing to password authentication.")
            return
        if self.auth_type.currentData() == "certificate":
            if (self._creating or auth_changed) and (not self.cert_path.text() or not self.key_path.text()):
                QMessageBox.warning(self, "Missing certificate", "Choose both the client certificate and private key.")
                return
        if (self._creating or self.change_proxy.isChecked()) and self.proxy_type.currentData() != "direct" and not self.proxy_server.text().strip():
            QMessageBox.warning(self, "Missing proxy", "Enter the proxy server hostname.")
            return
        self.accept()

    def set_profile(self, profile: AccountProfile) -> None:
        self.name.setText(profile.name)
        self.server.setText(profile.server)
        self.port.setValue(profile.port)
        self.hub.setText(profile.hub)
        self.username.setText(profile.username)
        self.nic.setCurrentText(profile.nic)
        self._select_data(self.auth_type, profile.auth_type)
        self.cert_path.setText(profile.certificate_path)
        self.key_path.setText(profile.private_key_path)
        self._select_data(self.proxy_type, profile.proxy_type)
        self.proxy_server.setText(profile.proxy_server)
        self.proxy_port.setValue(profile.proxy_port)
        self.proxy_username.setText(profile.proxy_username)
        self.change_proxy.setChecked(profile.change_proxy_settings)
        self.verify_cert.setChecked(profile.verify_server_certificate)
        self.encrypt.setChecked(profile.encrypt)
        self.compress.setChecked(profile.compress)
        self.max_tcp.setValue(profile.max_tcp)
        self.tcp_interval.setValue(profile.tcp_interval)
        self.tcp_ttl.setValue(profile.tcp_ttl)
        self.half_duplex.setChecked(profile.half_duplex)
        self.bridge_mode.setChecked(profile.bridge_mode)
        self.monitor_mode.setChecked(profile.monitor_mode)
        self.no_route.setChecked(profile.no_route_tracking)
        self.disable_qos.setChecked(profile.disable_qos)
        self.retry_count.setValue(profile.retry_count)
        self.retry_interval.setValue(profile.retry_interval)
        self.change_retry.setChecked(profile.change_retry_settings)
        self.startup.setChecked(profile.startup)
        self.change_startup.setChecked(profile.change_startup_setting)
        self.dhcp.setChecked(profile.dhcp_after_connect)
        self._update_enabled()

    @staticmethod
    def _select_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def profile(self) -> AccountProfile:
        return AccountProfile(
            name=self.name.text().strip(),
            server=self.server.text().strip(),
            port=self.port.value(),
            hub=self.hub.text().strip(),
            username=self.username.text().strip(),
            nic=self.nic.currentText().strip(),
            auth_type=str(self.auth_type.currentData()),
            password=self.password.text(),
            certificate_path=self.cert_path.text().strip(),
            private_key_path=self.key_path.text().strip(),
            proxy_type=str(self.proxy_type.currentData()),
            proxy_server=self.proxy_server.text().strip(),
            proxy_port=self.proxy_port.value(),
            proxy_username=self.proxy_username.text().strip(),
            proxy_password=self.proxy_password.text(),
            change_proxy_settings=self.change_proxy.isChecked(),
            verify_server_certificate=self.verify_cert.isChecked(),
            encrypt=self.encrypt.isChecked(),
            compress=self.compress.isChecked(),
            max_tcp=self.max_tcp.value(),
            tcp_interval=self.tcp_interval.value(),
            tcp_ttl=self.tcp_ttl.value(),
            half_duplex=self.half_duplex.isChecked(),
            bridge_mode=self.bridge_mode.isChecked(),
            monitor_mode=self.monitor_mode.isChecked(),
            no_route_tracking=self.no_route.isChecked(),
            disable_qos=self.disable_qos.isChecked(),
            retry_count=self.retry_count.value(),
            retry_interval=self.retry_interval.value(),
            change_retry_settings=self.change_retry.isChecked(),
            startup=self.startup.isChecked(),
            change_startup_setting=self.change_startup.isChecked(),
            dhcp_after_connect=self.dhcp.isChecked(),
        )


class StatusDialog(QDialog):
    def __init__(self, account_name: str, pairs: list[tuple[str, str]], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Connection Status of {account_name}")
        self.resize(650, 480)
        title = QLabel(f"<b>Status of VPN Session for {account_name}</b>")
        table = QTableWidget(len(pairs), 2)
        table.setHorizontalHeaderLabels(["Item", "Status"])
        table.verticalHeader().hide()
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for row, (key, value) in enumerate(pairs):
            table.setItem(row, 0, QTableWidgetItem(key))
            table.setItem(row, 1, QTableWidgetItem(value))
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeColumnToContents(0)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(table)
        layout.addWidget(buttons)


class PreferencesDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(720, 390)
        self.softether_dir = QLineEdit(config.softether_dir)
        self.softether_dir.setPlaceholderText("/usr/local/vpnclient")
        self.vpncmd = QLineEdit(config.vpncmd_path)
        self.vpnclient = QLineEdit(config.vpnclient_path)
        directory_button = QPushButton("Browse…")
        cmd_button = QPushButton("Browse…")
        client_button = QPushButton("Browse…")
        directory_button.clicked.connect(self._browse_directory)
        cmd_button.clicked.connect(lambda: self._browse(self.vpncmd))
        client_button.clicked.connect(lambda: self._browse(self.vpnclient))
        self.host = QLineEdit(config.management_host)
        self.close_to_tray = QCheckBox("Close window to notification area")
        self.close_to_tray.setChecked(config.close_to_tray)
        self.start_minimized = QCheckBox("Start minimized to notification area")
        self.start_minimized.setChecked(config.start_minimized)
        self.auto_start = QCheckBox("Offer to start the VPN Client service and reload existing settings when stopped")
        self.auto_start.setChecked(config.auto_start_client)
        self.default_dhcp = QCheckBox("Enable automatic DHCP for new connection settings")
        self.default_dhcp.setChecked(config.default_dhcp)

        directory_label = QLabel("SoftEther program directory:")
        directory_label.setToolTip("The folder containing vpncmd, vpnclient, and hamcore.se2")
        directory_hint = QLabel("This folder is used as the working directory so SoftEther can load hamcore.se2.")
        directory_hint.setWordWrap(True)

        form = QGridLayout()
        form.addWidget(directory_label, 0, 0)
        form.addWidget(self.softether_dir, 0, 1)
        form.addWidget(directory_button, 0, 2)
        form.addWidget(directory_hint, 1, 1, 1, 2)
        form.addWidget(QLabel("vpncmd executable:"), 2, 0)
        form.addWidget(self.vpncmd, 2, 1)
        form.addWidget(cmd_button, 2, 2)
        form.addWidget(QLabel("vpnclient executable:"), 3, 0)
        form.addWidget(self.vpnclient, 3, 1)
        form.addWidget(client_button, 3, 2)
        form.addWidget(QLabel("Management host:"), 4, 0)
        form.addWidget(self.host, 4, 1, 1, 2)
        form.addWidget(self.close_to_tray, 5, 0, 1, 3)
        form.addWidget(self.start_minimized, 6, 0, 1, 3)
        form.addWidget(self.auto_start, 7, 0, 1, 3)
        form.addWidget(self.default_dhcp, 8, 0, 1, 3)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch(1)
        layout.addWidget(buttons)

    def _browse_directory(self) -> None:
        start = self.softether_dir.text().strip() or str(Path(self.vpncmd.text()).parent)
        path = QFileDialog.getExistingDirectory(self, "Select SoftEther program directory", start)
        if not path:
            return
        self.softether_dir.setText(path)
        vpncmd = Path(path) / "vpncmd"
        vpnclient = Path(path) / "vpnclient"
        if vpncmd.is_file():
            self.vpncmd.setText(str(vpncmd))
        if vpnclient.is_file():
            self.vpnclient.setText(str(vpnclient))

    def _browse(self, target: QLineEdit) -> None:
        start = target.text().strip()
        if start:
            start = str(Path(start).parent)
        else:
            start = self.softether_dir.text().strip()
        path, _ = QFileDialog.getOpenFileName(self, "Select executable", start)
        if path:
            target.setText(path)

    def apply(self, config: AppConfig) -> None:
        config.softether_dir = self.softether_dir.text().strip()
        config.vpncmd_path = self.vpncmd.text().strip()
        config.vpnclient_path = self.vpnclient.text().strip()
        config.management_host = self.host.text().strip() or "localhost"
        config.close_to_tray = self.close_to_tray.isChecked()
        config.start_minimized = self.start_minimized.isChecked()
        config.auto_start_client = self.auto_start.isChecked()
        config.default_dhcp = self.default_dhcp.isChecked()
