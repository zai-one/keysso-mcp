"""Operator approvals for paid or writing calls: prepare -> operator accepts outside MCP -> apply.

The MCP tool only *prepares* an approval (stores the request digest). The operator accepts it
with ``keysso-approval --approval-id ID --digest DIGEST --accept``; the agent cannot. Apply
succeeds once, only for the exact same request, before the approval expires.

The server and the operator CLI are separate processes sharing one JSON file, so every
read-modify-write runs under an exclusive lock: without it an acceptance written from a stale
read could resurrect an approval the server had just consumed (a second paid call).

Every approval is bound to the principal that prepared it and to the provider binding (account,
API origin and credential fingerprint), so several servers sharing one state directory cannot
spend each other's approvals. Applying reserves the approval (state ``dispatched``); a request
that never left the server releases it, a definite provider answer settles it, and an ambiguous
failure (timeout, transport error, 5xx) keeps it as ``unknown`` for a day so the next approval
for the identical request is flagged ``previous_outcome_unknown`` for the operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

TTL_SECONDS = 30 * 60
# Dispatched or unknown-outcome records stay this long so a repeat can be flagged to the operator.
OUTCOME_TTL_SECONDS = 24 * 60 * 60
# Preparation needs no operator action, so pending approvals are bounded per principal and in
# total (count and stored request bytes): the store cannot grow without operator involvement.
MAX_PENDING_PER_PRINCIPAL = 20
MAX_PENDING_TOTAL = 200
MAX_PRINCIPAL_BYTES = 4 * 1024 * 1024
MAX_STORE_BYTES = 16 * 1024 * 1024


def request_digest(tool: str, request: dict[str, Any]) -> str:
    body = json.dumps({"tool": tool, "request": request}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class ApprovalQuotaExceeded(PermissionError):
    pass


def _size(request: dict[str, Any]) -> int:
    return len(json.dumps(request, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))


class ApprovalStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Exclusive cross-process lock on a sidecar file (fcntl on POSIX, msvcrt on Windows)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_name(self.path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                        break
                    except OSError:  # LK_LOCK gives up after ~10 s; keep waiting
                        continue
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)  # closing the descriptor releases the lock

    def operator_command(self, program: str, ticket: dict[str, Any]) -> str:
        """The exact accept command, pinned to this store's absolute path (cwd/env independent)."""
        return " ".join(
            [
                program,
                "--path",
                shlex.quote(str(self.path.absolute())),
                "--approval-id",
                ticket["approval_id"],
                "--digest",
                ticket["digest"],
                "--accept",
            ]
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        now = time.time()
        return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("expires", 0) > now}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".approvals-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def prepare(
        self,
        tool: str,
        request: dict[str, Any],
        summary: str,
        principal: str | None = None,
        binding: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any]:
        approval_id = uuid4().hex
        digest = request_digest(tool, request)
        size = _size(request)
        with self._locked():
            data = self._load()
            pending = [v for v in data.values() if not v.get("accepted") and not v.get("state")]
            own = [v for v in pending if v.get("principal") == principal]
            if (
                len(own) >= MAX_PENDING_PER_PRINCIPAL
                or len(pending) >= MAX_PENDING_TOTAL
                or sum(v.get("size", 0) for v in own) + size > MAX_PRINCIPAL_BYTES
                or sum(v.get("size", 0) for v in data.values()) + size > MAX_STORE_BYTES
            ):
                raise ApprovalQuotaExceeded(
                    "too many pending approvals; let the operator accept them or wait for expiry"
                )
            unknown = any(
                v.get("state") in {"dispatched", "unknown"}
                and v.get("digest") == digest
                and v.get("binding") == binding
                for v in data.values()
            )
            record: dict[str, Any] = {
                "tool": tool,
                "digest": digest,
                "summary": summary[:500],
                # The operator sees exactly what the digest covers (--list), not just a summary.
                "request": request,
                "principal": principal,
                "account": account,
                "binding": binding,
                "size": size,
                "accepted": False,
                "expires": time.time() + TTL_SECONDS,
            }
            if unknown:
                record["previous_outcome_unknown"] = True
            data[approval_id] = record
            self._save(data)
        ticket: dict[str, Any] = {"approval_id": approval_id, "digest": digest, "expires_in_s": TTL_SECONDS}
        if unknown:
            ticket["previous_outcome_unknown"] = True
        return ticket

    def accept(self, approval_id: str, digest: str) -> dict[str, Any]:
        with self._locked():
            data = self._load()
            record = data.get(approval_id)
            if record is None or record["digest"] != digest or record.get("state"):
                raise ValueError("approval not found, expired, already used or digest mismatch")
            record["accepted"] = True
            self._save(data)
        return {
            "approval_id": approval_id,
            "tool": record["tool"],
            "summary": record["summary"],
            "request": record.get("request"),
            "account": record.get("account"),
        }

    def consume(
        self,
        approval_id: str,
        tool: str,
        request: dict[str, Any],
        principal: str | None = None,
        binding: str | None = None,
    ) -> None:
        """Reserve a single-use approval: accepted, same tool, principal, binding and request.

        The record turns ``dispatched``; the caller must ``release`` it when the request never
        left the server, or ``settle`` it with the outcome.
        """
        with self._locked():
            data = self._load()
            record = data.get(str(approval_id))
            if record is None or not record.get("accepted") or record.get("state"):
                raise PermissionError("approval is not accepted by the operator (or expired)")
            if (
                record["tool"] != tool
                or record["digest"] != request_digest(tool, request)
                or record.get("principal") != principal
                or record.get("binding") != binding
            ):
                raise PermissionError("approval does not match this exact request")
            record["state"] = "dispatched"
            record["approval_expires"] = record["expires"]
            record["expires"] = time.time() + OUTCOME_TTL_SECONDS
            self._save(data)

    def release(self, approval_id: str) -> None:
        """The reserved request never reached Keys.so: the approval is usable again until it expires."""
        with self._locked():
            data = self._load()
            record = data.get(str(approval_id))
            if record is None or record.get("state") != "dispatched":
                return
            del record["state"]
            record["expires"] = record.pop("approval_expires", 0)
            if record["expires"] <= time.time():
                del data[str(approval_id)]
            self._save(data)

    def settle(self, approval_id: str, outcome: str) -> None:
        """Record the outcome of a dispatched request: ``unknown`` is kept, anything else is spent."""
        with self._locked():
            data = self._load()
            record = data.get(str(approval_id))
            if record is None or record.get("state") != "dispatched":
                return
            if outcome == "unknown":
                record["state"] = "unknown"
            else:
                del data[str(approval_id)]
            self._save(data)

    def pending(self) -> list[dict[str, Any]]:
        with self._locked():
            data = self._load()
        return [
            {"approval_id": k, **v} for k, v in data.items() if not v.get("accepted") and not v.get("state")
        ]


def main(argv: list[str] | None = None, *, default_path: Path) -> int:
    parser = argparse.ArgumentParser(description="Operator approval for paid/writing MCP calls")
    parser.add_argument("--path", type=Path, default=default_path)
    parser.add_argument("--list", action="store_true", help="show pending approvals")
    parser.add_argument("--approval-id")
    parser.add_argument("--digest")
    parser.add_argument("--accept", action="store_true")
    args = parser.parse_args(argv)
    store = ApprovalStore(args.path)
    if args.list or not args.accept:
        print(json.dumps(store.pending(), ensure_ascii=False, indent=2))
        return 0
    if not args.approval_id or not args.digest:
        parser.error("--accept needs --approval-id and --digest")
    print(json.dumps(store.accept(args.approval_id, args.digest), ensure_ascii=False))
    return 0


def default_path() -> Path:
    state = Path(os.environ.get("KEYSSO_STATE_PATH", "state/keysso.sqlite"))
    return state.with_name("keysso-approvals.json")


def cli() -> int:
    return main(default_path=default_path())


if __name__ == "__main__":
    raise SystemExit(cli())
