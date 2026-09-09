from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from zai_keysso.policy import PolicyStore
from zai_keysso.transport import ProviderAdmissionDenied


def test_replay_survives_new_store_and_failed_attempt(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    first = PolicyStore(path, "account", 10, 10)
    first.begin("exec1", "request", "actor", "hash", "nonce", time.time() + 60)
    first.finish("exec1", "error")
    second = PolicyStore(path, "account", 10, 10)
    with pytest.raises(PermissionError, match="already used"):
        second.begin("exec2", "request", "actor", "hash", "nonce", time.time() + 60)


def test_rate_admission_is_atomic_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    PolicyStore(path, "account", 3, 3, 20)

    def attempt(index: int) -> bool:
        store = PolicyStore(path, "account", 3, 3, 20)
        try:
            store.admit(str(index), "actor", 1)
            return True
        except ProviderAdmissionDenied:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(attempt, range(12))) == 3


def test_concurrency_and_cooldown_persist(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    first = PolicyStore(path, "account", 10, 10)
    first.admit("a", "actor", 1)
    second = PolicyStore(path, "account", 10, 10)
    with pytest.raises(ProviderAdmissionDenied, match="concurrency"):
        second.admit("b", "actor", 1)
    first.finish("a", "success")
    second.admit("b", "actor", 1)
    second.finish("b", "error")
    second.cooldown(3600)
    third = PolicyStore(path, "account", 10, 10)
    with pytest.raises(ProviderAdmissionDenied, match="cooldown"):
        third.admit("c", "actor", 1)


def test_principal_rate_does_not_allow_account_overspend(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "state.sqlite", "account", 2, 1, 10)
    store.admit("a", "alice", 1)
    with pytest.raises(ProviderAdmissionDenied):
        store.admit("b", "alice", 1)
    store.admit("c", "bob", 1)
    with pytest.raises(ProviderAdmissionDenied):
        store.admit("d", "carol", 1)
