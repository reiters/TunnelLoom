from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from PySide6.QtCore import QThread, QTimer, Qt, Slot
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStyle,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .backend import ClientPasswordRequired, SoftEtherBackend, VpncmdError
from .config import save_config
from .dialogs import AccountDialog, PreferencesDialog, StatusDialog
from .types import AppConfig, VirtualNic, VpnAccount
from .workers import Worker


@dataclass(slots=True)
class TaskContext:
    function: Callable[..., Any]
    message: str
    on_success: Callable[[Any], None] | None
    retry_after_password: bool
    offer_start_service: bool
    thread: QThread
    worker: Worker
    result_handled: bool = False
    thread_finished: bool = False


class MainWindow(QMainWindow):
    VPN_IP_COLUMN = 2

    def __init__(self, config: AppConfig, icon: QIcon, backend: SoftEtherBackend | None = None):
        super().__init__()
        self.config = config
        self.backend = backend or SoftEtherBackend(config)
        self._next_task_id = 0
        self._tasks: dict[int, TaskContext] = {}
        self.accounts: list[VpnAccount] = []
        self.nics: list[VirtualNic] = []
        # Preserve only the names across a deliberate service stop.  They are
        # used as a startup-settling hint; displayed rows still come exclusively
        # from fresh AccountList/NicList results.
        self._last_known_account_names: frozenset[str] = frozenset()
        self._last_known_nic_names: frozenset[str] = frozenset()
        self._busy = 0
        self._really_quit = False
        self._service_prompted = False
        self._service_running: bool | None = None
        self.setWindowTitle("TunnelLoom VPN Client Manager")
        self.setWindowIcon(icon)
        self.resize(1080, 600)
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_tables()
        self._create_tray(icon)
        self._update_actions()
        self.statusBar().showMessage("Ready")

        # Load the current SoftEther state once after the window is initialized.
        # Further refreshes are explicit: a user action, a successful change, or
        # the Refresh command. Deliberately do not poll in the background.
        QTimer.singleShot(200, self.refresh)

    def _create_actions(self) -> None:
        style = self.style()
        self.add_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_FileDialogNewFolder), "New VPN Connection Setting…", self)
        self.edit_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_FileDialogDetailedView), "Properties…", self)
        self.delete_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_TrashIcon), "Delete", self)
        self.connect_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_MediaPlay), "Connect", self)
        self.disconnect_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_MediaStop), "Disconnect", self)
        self.status_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxInformation), "View Status…", self)
        self.refresh_action = QAction(style.standardIcon(
            QStyle.StandardPixmap.SP_BrowserReload), "Refresh", self)
        self.import_action = QAction("Import VPN Connection Setting…", self)
        self.export_action = QAction("Export VPN Connection Setting…", self)
        self.new_nic_action = QAction("Create Virtual Network Adapter…", self)
        self.delete_nic_action = QAction(
            "Delete Virtual Network Adapter", self)
        self.enable_nic_action = QAction(
            "Enable Virtual Network Adapter", self)
        self.disable_nic_action = QAction(
            "Disable Virtual Network Adapter", self)
        self.mac_nic_action = QAction("Set MAC Address…", self)
        self.start_service_action = QAction("Start VPN Client Service", self)
        self.stop_service_action = QAction("Stop VPN Client Service", self)
        self.network_repair_action = QAction(
            "Repair Normal Network After VPN", self)
        self.network_diagnostics_action = QAction("Network Diagnostics…", self)
        self.preferences_action = QAction("Preferences…", self)
        self.about_action = QAction("About", self)
        self.quit_action = QAction("Exit VPN Client Manager", self)

        self.add_action.triggered.connect(self.add_account)
        self.edit_action.triggered.connect(self.edit_account)
        self.delete_action.triggered.connect(self.delete_account)
        self.connect_action.triggered.connect(self.connect_account)
        self.disconnect_action.triggered.connect(self.disconnect_account)
        self.status_action.triggered.connect(self.show_status)
        self.refresh_action.triggered.connect(self.refresh)
        self.import_action.triggered.connect(self.import_account)
        self.export_action.triggered.connect(self.export_account)
        self.new_nic_action.triggered.connect(self.create_nic)
        self.delete_nic_action.triggered.connect(self.delete_nic)
        self.enable_nic_action.triggered.connect(lambda: self.enable_nic(True))
        self.disable_nic_action.triggered.connect(
            lambda: self.enable_nic(False))
        self.mac_nic_action.triggered.connect(self.set_nic_mac)
        self.start_service_action.triggered.connect(self.start_client_service)
        self.stop_service_action.triggered.connect(
            lambda: self.run_task(
                self.backend.client_stop,
                "Stopping VPN Client service…",
                self._client_service_stopped,
                offer_start_service=False,
            )
        )
        self.network_repair_action.triggered.connect(
            self.repair_normal_network)
        self.network_diagnostics_action.triggered.connect(
            self.show_network_diagnostics)
        self.preferences_action.triggered.connect(self.preferences)
        self.about_action.triggered.connect(self.about)
        self.quit_action.triggered.connect(self.really_quit)

    def _create_menus(self) -> None:
        connect_menu = self.menuBar().addMenu("&Connect")
        connect_menu.addAction(self.add_action)
        connect_menu.addSeparator()
        connect_menu.addAction(self.connect_action)
        connect_menu.addAction(self.disconnect_action)
        connect_menu.addAction(self.status_action)
        connect_menu.addSeparator()
        connect_menu.addAction(self.import_action)
        connect_menu.addAction(self.export_action)
        connect_menu.addSeparator()
        connect_menu.addAction(self.quit_action)

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self.edit_action)
        edit_menu.addAction(self.delete_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.preferences_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.refresh_action)

        nic_menu = self.menuBar().addMenu("&Virtual Adapter")
        nic_menu.addAction(self.new_nic_action)
        nic_menu.addAction(self.delete_nic_action)
        nic_menu.addSeparator()
        nic_menu.addAction(self.enable_nic_action)
        nic_menu.addAction(self.disable_nic_action)
        nic_menu.addAction(self.mac_nic_action)

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self.start_service_action)
        tools_menu.addAction(self.stop_service_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.network_repair_action)
        tools_menu.addAction(self.network_diagnostics_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        for action in (
            self.add_action,
            self.edit_action,
            self.connect_action,
            self.disconnect_action,
            self.status_action,
            self.refresh_action,
        ):
            toolbar.addAction(action)
        self.addToolBar(toolbar)

    def _create_tables(self) -> None:
        self.account_table = QTableWidget(0, 6)
        self.account_table.setHorizontalHeaderLabels(
            [
                "VPN Connection Setting Name",
                "Status",
                "VPN IP Address",
                "VPN Server Hostname",
                "Virtual Hub",
                "Virtual Network Adapter",
            ]
        )
        self.account_table.verticalHeader().hide()
        self.account_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.account_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.account_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.account_table.horizontalHeader().setStretchLastSection(True)
        self.account_table.itemSelectionChanged.connect(self._update_actions)
        self.account_table.itemClicked.connect(self._account_cell_clicked)
        self.account_table.itemDoubleClicked.connect(
            lambda _item: self._account_double_click())
        self.account_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_table.customContextMenuRequested.connect(
            self._account_context_menu)

        self.nic_table = QTableWidget(0, 4)
        self.nic_table.setHorizontalHeaderLabels(
            ["Virtual Network Adapter Name", "Status", "MAC Address", "Version"])
        self.nic_table.verticalHeader().hide()
        self.nic_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.nic_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.nic_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.nic_table.horizontalHeader().setStretchLastSection(True)
        self.nic_table.itemSelectionChanged.connect(self._update_actions)
        self.nic_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nic_table.customContextMenuRequested.connect(
            self._nic_context_menu)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.account_table)
        splitter.addWidget(self.nic_table)
        splitter.setSizes([370, 180])
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(splitter)
        self.setCentralWidget(center)

    def _create_tray(self, icon: QIcon) -> None:
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("TunnelLoom VPN Client Manager")
        self.tray_menu = QMenu()
        self.tray_connections = self.tray_menu.addMenu("VPN Connections")
        self.tray_menu.addSeparator()
        show_action = self.tray_menu.addAction("Open VPN Client Manager")
        show_action.triggered.connect(self.show_and_raise)
        self.tray_menu.addAction(self.quit_action)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def run_task(
        self,
        function: Callable[..., Any],
        message: str,
        on_success: Callable[[Any], None] | None = None,
        retry_after_password: bool = True,
        offer_start_service: bool = False,
    ) -> None:
        self._next_task_id += 1
        task_id = self._next_task_id
        self._busy += 1
        self.statusBar().showMessage(message)

        thread = QThread(self)
        thread.setObjectName(f"SoftEtherTask-{task_id}")
        thread.setProperty("softetherTaskId", task_id)
        worker = Worker(task_id, function)
        worker.moveToThread(thread)
        self._tasks[task_id] = TaskContext(
            function=function,
            message=message,
            on_success=on_success,
            retry_after_password=retry_after_password,
            offer_start_service=offer_start_service,
            thread=thread,
            worker=worker,
        )

        thread.started.connect(worker.run)
        worker.finished.connect(self._task_finished)
        worker.failed.connect(self._task_failed)
        worker.done.connect(thread.quit)
        worker.done.connect(worker.deleteLater)
        thread.finished.connect(self._task_thread_finished)
        thread.start()

    @Slot(int, object)
    def _task_finished(self, task_id: int, result: Any) -> None:
        context = self._tasks.get(task_id)
        if context is None or context.result_handled:
            return
        context.result_handled = True
        self._busy = max(0, self._busy - 1)
        self.statusBar().showMessage("Ready", 3000)
        try:
            if context.on_success:
                context.on_success(result)
        except Exception as exc:
            self._show_exception(exc)
        finally:
            self._maybe_release_task(task_id)

    @Slot(int, object)
    def _task_failed(self, task_id: int, exc: Exception) -> None:
        context = self._tasks.get(task_id)
        if context is None or context.result_handled:
            return
        context.result_handled = True
        self._busy = max(0, self._busy - 1)

        try:
            if isinstance(exc, ClientPasswordRequired) and context.retry_after_password:
                password, ok = QInputDialog.getText(
                    self,
                    "VPN Client Management Password",
                    "Enter the management password for the local SoftEther VPN Client service:",
                    QLineEdit.EchoMode.Password,
                )
                if ok:
                    self.backend.set_management_password(password)
                    self.run_task(
                        context.function,
                        context.message,
                        context.on_success,
                        retry_after_password=False,
                        offer_start_service=context.offer_start_service,
                    )
                return

            if (
                context.offer_start_service
                and self.config.auto_start_client
                and not self._service_prompted
                and isinstance(exc, VpncmdError)
            ):
                self._service_prompted = True
                details = str(exc)
                if exc.result:
                    details += " " + exc.result.output + " " + exc.result.stderr
                if any(
                    token in details.casefold()
                    for token in ("connection", "refused", "vpn client service", "error 1")
                ):
                    answer = QMessageBox.question(
                        self,
                        "VPN Client Service",
                        "The SoftEther VPN Client service does not appear to be running. Start it now?",
                    )
                    if answer == QMessageBox.Yes:

                        def service_ready(state: tuple[list[VpnAccount], list[VirtualNic]]) -> None:
                            self._service_prompted = False
                            self._apply_state(state)
                            self.run_task(
                                context.function,
                                context.message,
                                context.on_success,
                                retry_after_password=context.retry_after_password,
                                offer_start_service=False,
                            )

                        self.run_task(
                            partial(
                                self.backend.client_start_and_load_state,
                                self._last_known_account_names,
                                self._last_known_nic_names,
                            ),
                            "Starting VPN Client service and loading existing settings…",
                            service_ready,
                            offer_start_service=False,
                        )
                        return

            self.statusBar().showMessage("Operation failed", 5000)
            self._show_exception(exc)
        finally:
            self._maybe_release_task(task_id)

    @Slot()
    def _task_thread_finished(self) -> None:
        thread = self.sender()
        if not isinstance(thread, QThread):
            return
        value = thread.property("softetherTaskId")
        try:
            task_id = int(value)
        except (TypeError, ValueError):
            return
        context = self._tasks.get(task_id)
        if context is None:
            thread.deleteLater()
            return
        context.thread_finished = True
        self._maybe_release_task(task_id)

    def _maybe_release_task(self, task_id: int) -> None:
        context = self._tasks.get(task_id)
        if context is None or not (context.result_handled and context.thread_finished):
            return
        self._tasks.pop(task_id, None)
        context.thread.deleteLater()

    def _show_exception(self, exc: Exception) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("TunnelLoom VPN Client Manager")
        box.setText(str(exc))
        if isinstance(exc, VpncmdError) and exc.result:
            detail = (exc.result.output + "\n" + exc.result.stderr).strip()
            if detail:
                box.setDetailedText(detail)
        box.exec()

    def refresh(self) -> None:
        self._begin_refresh(allow_empty=False)

    def refresh_allowing_empty(self) -> None:
        """Refresh after a known delete operation where an empty list is valid."""
        self._begin_refresh(allow_empty=True)

    def _begin_refresh(self, allow_empty: bool) -> None:
        if self._busy:
            return
        # Keep the current rows visible while the backend obtains and validates
        # a replacement snapshot.  A stopped service is handled separately.
        self.run_task(
            partial(
                self.backend.load_stable_state_if_running,
                self._last_known_account_names,
                self._last_known_nic_names,
            ),
            "Refreshing VPN Client status…",
            partial(self._apply_refresh_result, allow_empty=allow_empty),
            offer_start_service=False,
        )

    def _apply_refresh_result(
        self,
        state: tuple[list[VpnAccount], list[VirtualNic]] | None,
        *,
        allow_empty: bool = False,
    ) -> None:
        if state is None:
            self._client_service_stopped(None)
            return

        accounts, nics = state
        retained: list[str] = []
        # An isolated successful-but-empty SoftEther response is not enough to
        # erase rows already known to exist.  Preserve each section independently
        # so a valid status update in the other section can still be displayed.
        if not allow_empty and self.accounts and not accounts:
            accounts = self.accounts
            retained.append("connection settings")
        if not allow_empty and self.nics and not nics:
            nics = self.nics
            retained.append("virtual adapters")

        self._apply_state((accounts, nics))
        if retained:
            sections = " and ".join(retained)
            self.statusBar().showMessage(
                f"SoftEther returned an empty {sections} list; previous rows were retained.",
                8000,
            )

    def _apply_state(self, state: tuple[list[VpnAccount], list[VirtualNic]]) -> None:
        self._service_prompted = False
        self._service_running = True
        accounts, nics = state
        selected_account = self.selected_account().name if self.selected_account() else ""
        selected_nic = self.selected_nic().name if self.selected_nic() else ""
        self.accounts = accounts
        self.nics = nics
        self._last_known_account_names = frozenset(
            item.name for item in accounts)
        self._last_known_nic_names = frozenset(item.name for item in nics)
        self.account_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            values = (
                account.name,
                account.status,
                account.vpn_ip or "—",
                account.server,
                account.hub,
                account.nic,
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, account.name)
                if col == self.VPN_IP_COLUMN and account.vpn_ip:
                    item.setToolTip("Click to copy this VPN IP address")
                self.account_table.setItem(row, col, item)
            if account.name == selected_account:
                self.account_table.selectRow(row)
        self.account_table.resizeColumnsToContents()
        self.nic_table.setRowCount(len(nics))
        for row, nic in enumerate(nics):
            values = (nic.name, nic.status, nic.mac, nic.version)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, nic.name)
                self.nic_table.setItem(row, col, item)
            if nic.name == selected_nic:
                self.nic_table.selectRow(row)
        self.nic_table.resizeColumnsToContents()
        self._rebuild_tray_connections()
        self._update_actions()
        connected = sum(1 for item in accounts if item.is_connected)
        self.statusBar().showMessage(
            f"{len(accounts)} connection settings, {connected} connected, {len(nics)} virtual adapters", 5000)

    @Slot(object)
    def _account_cell_clicked(self, item: QTableWidgetItem) -> None:
        if item.column() != self.VPN_IP_COLUMN:
            return
        address = item.text().strip()
        if not address or address == "—":
            return
        QApplication.clipboard().setText(address)
        self.statusBar().showMessage(
            f"Copied VPN IP address {address} to the clipboard", 4000)

    def selected_account(self) -> VpnAccount | None:
        row = self.account_table.currentRow()
        if row < 0 or row >= len(self.accounts):
            return None
        name_item = self.account_table.item(row, 0)
        if not name_item:
            return None
        name = name_item.data(Qt.UserRole)
        return next((item for item in self.accounts if item.name == name), None)

    def selected_nic(self) -> VirtualNic | None:
        row = self.nic_table.currentRow()
        if row < 0 or row >= len(self.nics):
            return None
        name_item = self.nic_table.item(row, 0)
        if not name_item:
            return None
        name = name_item.data(Qt.UserRole)
        return next((item for item in self.nics if item.name == name), None)

    def _update_actions(self) -> None:
        account = self.selected_account()
        nic = self.selected_nic()
        running = self._service_running is True
        self.start_service_action.setEnabled(not running)
        self.stop_service_action.setEnabled(running)
        self.add_action.setEnabled(running)
        self.import_action.setEnabled(running)
        self.new_nic_action.setEnabled(running)
        self.edit_action.setEnabled(
            running and account is not None and not account.is_active)
        self.delete_action.setEnabled(running and account is not None)
        self.connect_action.setEnabled(
            running and account is not None and not account.is_active)
        self.disconnect_action.setEnabled(
            running and account is not None and account.is_active)
        self.status_action.setEnabled(
            running and account is not None and account.is_active)
        self.export_action.setEnabled(running and account is not None)
        self.delete_nic_action.setEnabled(running and nic is not None)
        self.enable_nic_action.setEnabled(
            running and nic is not None and nic.status.casefold() != "enabled")
        self.disable_nic_action.setEnabled(
            running and nic is not None and nic.status.casefold() == "enabled")
        self.mac_nic_action.setEnabled(running and nic is not None)

    def add_account(self) -> None:
        dialog = AccountDialog(self.nics, parent=self)
        if dialog.exec():
            profile = dialog.profile()
            self.run_task(partial(self.backend.create_account, profile),
                          "Creating VPN connection setting…", lambda _r: self.refresh())

    def edit_account(self) -> None:
        account = self.selected_account()
        if not account:
            return

        def loaded(profile: Any) -> None:
            dialog = AccountDialog(self.nics, profile, self)
            if dialog.exec():
                updated = dialog.profile()
                self.run_task(
                    partial(self.backend.update_account,
                            account.name, updated),
                    "Saving VPN connection setting…",
                    lambda _r: self.refresh(),
                )

        self.run_task(partial(self.backend.get_profile, account.name),
                      "Loading connection properties…", loaded)

    def delete_account(self) -> None:
        account = self.selected_account()
        if not account:
            return
        answer = QMessageBox.question(
            self,
            "Delete VPN Connection Setting",
            f'Delete the VPN connection setting "{account.name}"?',
        )
        if answer == QMessageBox.Yes:
            self.run_task(partial(self.backend.delete_account, account.name),
                          "Deleting connection setting…", lambda _r: self.refresh_allowing_empty())

    def connect_account(self) -> None:
        account = self.selected_account()
        if account:
            self.run_task(
                partial(self.backend.connect, account),
                f'Connecting to "{account.name}"…',
                lambda _r: self.refresh(),
                offer_start_service=True,
            )

    def disconnect_account(self) -> None:
        account = self.selected_account()
        if account:
            self.run_task(partial(self.backend.disconnect, account),
                          f'Disconnecting "{account.name}"…', lambda _r: self.refresh())

    def _client_service_stopped(self, _result: Any) -> None:
        # The stopped service cannot answer AccountList or NicList. Clear the
        # displayed state and present it as a normal status rather than an error.
        self._service_running = False
        self.accounts = []
        self.nics = []
        self.account_table.setRowCount(0)
        self.nic_table.setRowCount(0)
        self._rebuild_tray_connections()
        self._update_actions()
        self.statusBar().showMessage("VPN Client service is stopped")

    def start_client_service(self) -> None:
        def loaded(state: tuple[list[VpnAccount], list[VirtualNic]]) -> None:
            self._service_prompted = False
            self._apply_state(state)

        self.run_task(
            partial(
                self.backend.client_start_and_load_state,
                self._last_known_account_names,
                self._last_known_nic_names,
            ),
            "Starting VPN Client service and loading existing settings…",
            loaded,
            offer_start_service=False,
        )

    def show_status(self) -> None:
        account = self.selected_account()
        if not account:
            return
        self.run_task(
            partial(self.backend.get_status, account.name),
            "Loading connection status…",
            lambda pairs: StatusDialog(account.name, pairs, self).exec(),
        )

    def export_account(self) -> None:
        account = self.selected_account()
        if not account:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export VPN Connection Setting", f"{account.name}.vpn", "VPN files (*.vpn);;All files (*)")
        if path:
            self.run_task(partial(self.backend.export_account,
                          account.name, path), "Exporting connection setting…")

    def import_account(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import VPN Connection Setting", "", "VPN files (*.vpn);;All files (*)")
        if path:
            self.run_task(partial(self.backend.import_account, path),
                          "Importing connection setting…", lambda _r: self.refresh())

    def create_nic(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Create New Virtual Network Adapter", "Virtual Network Adapter Name:")
        if ok and name.strip():
            self.run_task(partial(self.backend.create_nic, name.strip(
            )), "Creating virtual network adapter…", lambda _r: self.refresh())

    def delete_nic(self) -> None:
        nic = self.selected_nic()
        if not nic:
            return
        if QMessageBox.question(self, "Delete Virtual Network Adapter", f'Delete virtual adapter "{nic.name}"?') == QMessageBox.Yes:
            self.run_task(partial(self.backend.delete_nic, nic.name),
                          "Deleting virtual network adapter…", lambda _r: self.refresh_allowing_empty())

    def enable_nic(self, enabled: bool) -> None:
        nic = self.selected_nic()
        if nic:
            self.run_task(partial(self.backend.enable_nic, nic.name, enabled),
                          "Updating virtual network adapter…", lambda _r: self.refresh())

    def set_nic_mac(self) -> None:
        nic = self.selected_nic()
        if not nic:
            return
        current = nic.mac
        if len(current) == 12 and ":" not in current:
            current = ":".join(current[index:index + 2]
                               for index in range(0, 12, 2))
        value, ok = QInputDialog.getText(
            self, "Virtual Network Adapter MAC Address", "MAC address:", text=current)
        if ok and value.strip():
            self.run_task(partial(self.backend.set_nic_mac, nic.name, value.strip(
            )), "Changing MAC address…", lambda _r: self.refresh())

    def repair_normal_network(self) -> None:
        if any(account.is_active for account in self.accounts):
            QMessageBox.warning(
                self,
                "Repair Normal Network",
                "Disconnect active VPN connections before repairing the normal network.",
            )
            return
        self.run_task(
            self.backend.repair_network,
            "Repairing normal routes and DNS…",
            self._show_network_repair_result,
            offer_start_service=False,
        )

    def _show_network_repair_result(self, result: Any) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Normal Network Repair")
        box.setText(
            "Normal routes and DNS were checked and repaired where necessary.")
        detail = (getattr(result, "output", "") + "\n" +
                  getattr(result, "stderr", "")).strip()
        if detail:
            box.setDetailedText(detail)
        box.exec()

    def show_network_diagnostics(self) -> None:
        self.run_task(
            self.backend.network_diagnostics,
            "Collecting network diagnostics…",
            self._show_network_diagnostics_result,
            offer_start_service=False,
        )

    def _show_network_diagnostics_result(self, result: Any) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Network Diagnostics")
        box.setText(
            "Current routes, interfaces, NetworkManager state, and resolver configuration are shown below.")
        detail = (getattr(result, "output", "") + "\n" +
                  getattr(result, "stderr", "")).strip()
        box.setDetailedText(detail or "No diagnostic output was returned.")
        box.exec()

    def preferences(self) -> None:
        dialog = PreferencesDialog(self.config, self)
        if dialog.exec():
            dialog.apply(self.config)
            save_config(self.config)
            self.refresh()

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About TunnelLoom VPN Client Manager",
            f"<b>TunnelLoom VPN Client Manager for Linux {__version__}</b><br><br>"
            "An unofficial PySide6 desktop interface for the SoftEther VPN Client service and vpncmd. "
            "It is not affiliated with the SoftEther Project.<br><br>"
            "The interface uses SoftEther's documented VPN Client management commands and adds Linux DHCP integration.",
        )

    def _account_double_click(self) -> None:
        account = self.selected_account()
        if not account:
            return
        if account.is_connected:
            self.show_status()
        elif account.is_active:
            self.disconnect_account()
        else:
            self.connect_account()

    def _account_context_menu(self, point: Any) -> None:
        menu = QMenu(self)
        menu.addAction(self.connect_action)
        menu.addAction(self.disconnect_action)
        menu.addAction(self.status_action)
        menu.addSeparator()
        menu.addAction(self.edit_action)
        menu.addAction(self.delete_action)
        menu.exec(self.account_table.viewport().mapToGlobal(point))

    def _nic_context_menu(self, point: Any) -> None:
        menu = QMenu(self)
        menu.addAction(self.enable_nic_action)
        menu.addAction(self.disable_nic_action)
        menu.addAction(self.mac_nic_action)
        menu.addSeparator()
        menu.addAction(self.delete_nic_action)
        menu.exec(self.nic_table.viewport().mapToGlobal(point))

    def _rebuild_tray_connections(self) -> None:
        self.tray_connections.clear()
        if not self.accounts:
            empty = self.tray_connections.addAction("No connection settings")
            empty.setEnabled(False)
            return
        for account in self.accounts:
            submenu = self.tray_connections.addMenu(
                f"{account.name} — {account.status}")
            connect = submenu.addAction("Connect")
            disconnect = submenu.addAction("Disconnect")
            connect.setEnabled(not account.is_active)
            disconnect.setEnabled(account.is_active)
            connect.triggered.connect(
                partial(self._tray_connect, account.name, True))
            disconnect.triggered.connect(
                partial(self._tray_connect, account.name, False))

    def _tray_connect(self, account_name: str, connect: bool) -> None:
        account = next(
            (item for item in self.accounts if item.name == account_name), None)
        if not account:
            return
        function = partial(
            self.backend.connect if connect else self.backend.disconnect, account)
        self.run_task(function, ("Connecting " if connect else "Disconnecting ") +
                      account_name, lambda _r: self.refresh())

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            self.show_and_raise()

    def show_and_raise(self) -> None:
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.config.close_to_tray and not self._really_quit and self.tray.isVisible():
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "TunnelLoom VPN Client Manager",
                "The manager is still running in the notification area.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
        else:
            event.accept()

    def really_quit(self) -> None:
        self._really_quit = True
        self.tray.hide()
        QApplication.quit()
