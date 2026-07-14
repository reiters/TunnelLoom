from pathlib import Path


def test_main_window_has_no_periodic_refresh_timer():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert "timer.timeout.connect" not in source
    assert ".timer.start(" not in source
    assert "QTimer.singleShot(200, self.refresh)" in source


def test_refresh_interval_setting_removed():
    root = Path(__file__).resolve().parents[1]
    assert "refresh_seconds" not in (root / "softether_gui" / "types.py").read_text(encoding="utf-8")
    assert "Refresh interval" not in (root / "softether_gui" / "dialogs.py").read_text(encoding="utf-8")


def test_stopping_service_does_not_immediately_query_stopped_service():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert "self._client_service_stopped" in source
    assert 'self.backend.client_stop, "Stopping VPN Client service…", self.refresh' not in source


def test_refresh_uses_vpncmd_state_loader_without_periodic_polling():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    backend_source = (Path(__file__).resolve().parents[1] / "softether_gui" / "backend.py").read_text(encoding="utf-8")
    assert "self.backend.load_stable_state_if_running" in source
    assert "self._apply_refresh_result" in source
    assert 'offer_start_service=False' in source
    stable_block = backend_source.split("def load_stable_state_if_running", 1)[1].split("def wait_for_state", 1)[0]
    assert "client_is_running" not in stable_block
    assert "self.load_state()" in stable_block


def test_stopped_refresh_is_presented_as_normal_status():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert 'self._service_running = False' in source
    assert 'VPN Client service is stopped' in source



def test_service_restart_waits_for_previously_visible_settings():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert "self._last_known_account_names" in source
    assert "self._last_known_nic_names" in source
    assert "partial(\n                self.backend.client_start_and_load_state" in source


def test_refresh_uses_stable_snapshot_and_retains_unexpected_empty_lists():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert "self.backend.load_stable_state_if_running" in source
    assert "previous rows were retained" in source
    assert "if not allow_empty and self.accounts and not accounts" in source
    assert "if not allow_empty and self.nics and not nics" in source


def test_known_delete_operations_allow_empty_refresh_results():
    source = (Path(__file__).resolve().parents[1] / "softether_gui" / "main_window.py").read_text(encoding="utf-8")
    assert source.count("refresh_allowing_empty") >= 3
