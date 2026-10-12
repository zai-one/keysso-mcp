"""Read-only update suggestion: compare the installed version with the latest GitHub release.

Never installs anything. One unauthenticated HTTPS GET to the public GitHub API, a short
timeout, a ~24h local cache and graceful failure offline. Every attempt is recorded in the
cache: after a failure the next fetch waits 30 minutes, and a forced refresh is honoured at
most once a minute. Opt out with KEYSSO_DISABLE_UPDATE_CHECK=1.
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from zai_keysso import __version__

REPOSITORY = "zai-one/keysso-mcp"
DISTRIBUTION = "zai-keysso-mcp"
WHEEL_PREFIX = "zai_keysso_mcp"
DISPLAY_NAME = "Keysso MCP"
CHECK_TOOL = "keysso_check_update"
ENV_DISABLE = "KEYSSO_DISABLE_UPDATE_CHECK"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
CACHE_FILE = "update-check.json"
CACHE_TTL_SECONDS = 24 * 3600
FAILURE_BACKOFF_SECONDS = 30 * 60
FORCE_MIN_INTERVAL_SECONDS = 60
TIMEOUT_SECONDS = 3.0
# Plain release tags only (ASCII digits, up to four parts). Anything else is treated as "no release".
_VERSION = r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}"
_TAG = re.compile(rf"v?({_VERSION})")
_PLAIN = re.compile(_VERSION)
_RELEASE_URL = re.compile(rf"{re.escape(RELEASES_URL)}(?:/tag/v?{_VERSION})?")
_ERROR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_TRUE = {"1", "true", "yes", "on"}

Fetch = Callable[[], dict[str, Any]]


def disabled() -> bool:
    return os.environ.get(ENV_DISABLE, "").strip().casefold() in _TRUE


def parse_version(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, str):
        return None
    match = _TAG.fullmatch(value)
    if match is None:
        return None
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def update_command(version: str) -> str:
    wheel = f"{WHEEL_PREFIX}-{version}-py3-none-any.whl"
    url = f"https://github.com/{REPOSITORY}/releases/download/v{version}/{wheel}"
    return f'uv tool install --force "{DISTRIBUTION} @ {url}"'


def fetch_latest_release() -> dict[str, Any]:
    response = httpx.get(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{DISTRIBUTION}/{__version__} update-check",
        },
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > 1_000_000:
        raise ValueError("release metadata too large")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("unexpected release metadata")
    return payload


def _timestamp(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _release_record(payload: dict[str, Any], now: float) -> dict[str, Any]:
    tag = payload.get("tag_name")
    match = _TAG.fullmatch(tag) if isinstance(tag, str) else None
    if match is None or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("latest release has no stable version tag")
    url = payload.get("html_url")
    if not isinstance(url, str) or _RELEASE_URL.fullmatch(url) is None:
        url = RELEASES_URL
    return {"latest_version": match.group(1), "release_url": url, "checked_at": now}


def _good_record(data: dict[str, Any]) -> dict[str, Any] | None:
    latest, url, checked = data.get("latest_version"), data.get("release_url"), data.get("checked_at")
    if (
        not isinstance(latest, str)
        or _PLAIN.fullmatch(latest) is None
        or not isinstance(url, str)
        or _RELEASE_URL.fullmatch(url) is None
        or not _timestamp(checked)
    ):
        return None
    return {"latest_version": latest, "release_url": url, "checked_at": checked}


def _read_state(path: Path) -> dict[str, Any]:
    """Last good release (validated like fresh metadata) plus the last attempt time and outcome."""
    state: dict[str, Any] = {"good": None, "attempted_at": None, "last_error": None}
    try:
        if path.stat().st_size > 4096:
            return state
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if not isinstance(data, dict):
        return state
    good = _good_record(data)
    state["good"] = good
    attempted = data.get("attempted_at")
    if _timestamp(attempted):
        state["attempted_at"] = attempted
    elif good is not None:
        state["attempted_at"] = good["checked_at"]
    error = data.get("last_error")
    if isinstance(error, str) and _ERROR_NAME.fullmatch(error):
        state["last_error"] = error
    elif error is not None or (good is None and state["attempted_at"] is not None):
        state["last_error"] = "Error"
    return state


def _write_state(path: Path, good: dict[str, Any] | None, attempted_at: float, error: str | None) -> None:
    record = {**(good or {}), "attempted_at": attempted_at, "last_error": error}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # The cache is an optimisation; never fail the caller.


def _within(start: float | None, now: float, seconds: float) -> bool:
    return start is not None and 0 <= now - start < seconds


def _fresh(state: dict[str, Any], now: float) -> bool:
    good = state["good"]
    return good is not None and _within(good["checked_at"], now, CACHE_TTL_SECONDS)


def _fetch_due(state: dict[str, Any], now: float, force: bool) -> bool:
    if force:
        return not _within(state["attempted_at"], now, FORCE_MIN_INTERVAL_SECONDS)
    if _fresh(state, now):
        return False
    return not (state["last_error"] and _within(state["attempted_at"], now, FAILURE_BACKOFF_SECONDS))


def _view(record: dict[str, Any], source: str) -> dict[str, Any]:
    latest = record["latest_version"]
    current, newest = parse_version(__version__), parse_version(latest)
    available = bool(current is not None and newest is not None and newest > current)
    return {
        "enabled": True,
        "status": "ok",
        "source": source,
        "current_version": __version__,
        "latest_version": latest,
        "update_available": available,
        "release_url": record["release_url"],
        "update_command": update_command(latest) if available else None,
        "checked_at_unix": int(record["checked_at"]),
        "auto_update": False,
        "note": "Suggestion only; nothing is installed automatically. Restart the MCP client after updating.",
    }


def _unavailable(error: str, good: dict[str, Any] | None, retry_after: float | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "enabled": True,
        "status": "unavailable",
        "current_version": __version__,
        "update_available": None,
        "error": error,
        "releases_url": RELEASES_URL,
    }
    if retry_after is not None:
        result["retry_after_unix"] = int(retry_after)
    if good is not None:
        result["last_known"] = _view(good, "stale_cache")
    return result


def check_update(
    cache_path: Path, *, force: bool = False, fetch: Fetch | None = None, now: float | None = None
) -> dict[str, Any]:
    """Return current/latest version and an update command; never raises."""
    if disabled():
        return {
            "enabled": False,
            "status": "disabled",
            "current_version": __version__,
            "update_available": None,
            "note": f"Update checks are disabled by {ENV_DISABLE}.",
        }
    now = time.time() if now is None else now
    state = _read_state(cache_path)
    good = state["good"]
    if not _fetch_due(state, now, force):
        if good is not None and (_fresh(state, now) or state["last_error"] is None):
            return _view(good, "cache")
        attempted = state["attempted_at"] if state["attempted_at"] is not None else now
        wait = FORCE_MIN_INTERVAL_SECONDS if force else FAILURE_BACKOFF_SECONDS
        return _unavailable(state["last_error"] or "Throttled", good, attempted + wait)
    fetch = fetch_latest_release if fetch is None else fetch
    try:
        record = _release_record(fetch(), now)
    except Exception as exc:  # offline, rate limited, malformed: degrade quietly
        error = type(exc).__name__
        error = error if _ERROR_NAME.fullmatch(error) else "Error"
        _write_state(cache_path, good, now, error)
        return _unavailable(error, good)
    _write_state(cache_path, record, now, None)
    return _view(record, "github")


def cached_hint(cache_path: Path) -> str | None:
    """Short startup hint from the local cache only; never touches the network."""
    if disabled():
        return None
    good = _read_state(cache_path)["good"]
    if good is None:
        return None
    view = _view(good, "cache")
    if not view["update_available"]:
        return None
    return (
        f"{DISPLAY_NAME} {view['latest_version']} is available (installed {__version__}). "
        f"Mention it once to the user if relevant; {CHECK_TOOL} returns release notes and the update command."
    )


def refresh_in_background(cache_path: Path) -> threading.Thread | None:
    """Refresh a stale cache in a daemon thread so the next start can show a hint.

    Obeys the same rules as the tool: a fresh cache or a failure in the last 30 minutes skips it.
    """
    if disabled() or not _fetch_due(_read_state(cache_path), time.time(), False):
        return None
    thread = threading.Thread(target=check_update, args=(cache_path,), name="update-check", daemon=True)
    thread.start()
    return thread
