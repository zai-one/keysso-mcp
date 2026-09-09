from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def read_secret_file(value: str) -> str:
    if not value:
        raise ValueError("a credential file must be configured")
    path = Path(value)
    if not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("credential file is missing or too large")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("credential file must be private to its owner")
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise ValueError("credential file is empty")
    return secret


@dataclass(frozen=True)
class ServiceConfig:
    provider_token: str = field(repr=False)
    state_path: Path
    base_url: str = "https://api.keys.so"
    account_id: str = "default"
    principal_id: str = "local-operator"
    auth_mode: str = "operator"
    public_key: str = ""
    issuer: str = "keysso-operator"
    audience: str = "keysso-mcp"
    rate_limit: int = 10
    principal_rate_limit: int = 10
    max_concurrency: int = 1
    delegated_ttl: int = 60

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("provider base URL must be an HTTPS origin without credentials")
        if not self.provider_token or len(self.provider_token) > 4096:
            raise ValueError("provider token is missing or invalid")
        if self.auth_mode not in {"operator", "delegated"}:
            raise ValueError("auth_mode must be operator or delegated")
        if not self.account_id or not self.principal_id or not self.issuer or not self.audience:
            raise ValueError("identity fields must be nonempty")
        if not 1 <= self.principal_rate_limit <= self.rate_limit <= 10000:
            raise ValueError("invalid request rate limits")
        if not 1 <= self.max_concurrency <= 100:
            raise ValueError("invalid concurrency limit")
        if not 1 <= self.delegated_ttl <= 300:
            raise ValueError("invalid delegated TTL")

    @classmethod
    def from_env(cls) -> ServiceConfig:
        public_file = os.environ.get("KEYSSO_MCP_PUBLIC_KEY_FILE", "")
        return cls(
            provider_token=read_secret_file(os.environ.get("KEYSSO_API_TOKEN_FILE", "")),
            state_path=Path(os.environ.get("KEYSSO_STATE_PATH", "state/keysso.sqlite")),
            base_url=os.environ.get("KEYSSO_API_BASE_URL", "https://api.keys.so"),
            account_id=os.environ.get("KEYSSO_ACCOUNT_ID", "default"),
            principal_id=os.environ.get("KEYSSO_LOCAL_PRINCIPAL", "local-operator"),
            auth_mode=os.environ.get("KEYSSO_AUTH_MODE", "operator"),
            public_key=Path(public_file).read_text(encoding="utf-8") if public_file else "",
            issuer=os.environ.get("KEYSSO_MCP_ISSUER", "keysso-operator"),
            audience=os.environ.get("KEYSSO_MCP_AUDIENCE", "keysso-mcp"),
            rate_limit=int(os.environ.get("KEYSSO_RATE_LIMIT", "10")),
            principal_rate_limit=int(os.environ.get("KEYSSO_PRINCIPAL_RATE_LIMIT", "10")),
            max_concurrency=int(os.environ.get("KEYSSO_MAX_CONCURRENCY", "1")),
        )
