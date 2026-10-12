import pytest


@pytest.fixture(autouse=True)
def _no_update_check_network(monkeypatch):
    """Keep every test offline: the update check is disabled unless a test re-enables it."""
    monkeypatch.setenv("KEYSSO_DISABLE_UPDATE_CHECK", "1")
