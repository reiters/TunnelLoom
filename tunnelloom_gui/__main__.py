from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .backend import SoftEtherBackend
from .config import load_config
from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("TunnelLoom VPN Client Manager")
    app.setOrganizationName("TunnelLoom GUI Community")
    app.setQuitOnLastWindowClosed(False)
    icon_path = Path(__file__).resolve().parent.parent / \
        "assets" / "tunnelloom-gui.svg"
    icon = QIcon(str(icon_path))
    app.setWindowIcon(icon)

    config = load_config()
    backend = SoftEtherBackend(config)

    # Ask for administrator authorization before creating or showing the main
    # window. pkexec displays the native PolicyKit dialog through the desktop
    # agent; once approved, the same helper session is reused by all refreshes and commands
    # until the application exits.
    try:
        backend.authorize()
    except Exception as exc:
        backend.close()
        QMessageBox.critical(
            None,
            "SoftEther Administrator Authorization",
            "Administrator authorization is required to use the SoftEther VPN "
            f"Client Manager.\n\n{exc}",
        )
        return 1

    window = MainWindow(config, icon, backend=backend)
    app.aboutToQuit.connect(window.backend.close)
    if config.start_minimized and window.tray.isVisible():
        window.hide()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
