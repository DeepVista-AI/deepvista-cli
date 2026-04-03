"""Token load / save / refresh logic.

Storage: ~/.config/deepvista/credentials.json (mode 0600)

Token refresh uses the issuer URL from the JWT itself, so the CLI always
refreshes against the correct Supabase instance (production vs staging).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from filelock import FileLock

from deepvista_cli.config import CONFIG_DIR
from deepvista_cli.config import credentials_path as _default_creds_path

logger = logging.getLogger(__name__)

REFRESH_BUFFER_SECONDS = 60  # refresh when <60s remaining


def _extract_issuer(access_token: str) -> str | None:
    """Extract the `iss` claim from a JWT without verifying the signature.

    The issuer looks like ``https://xyz.supabase.co/auth/v1`` and tells us
    which Supabase instance issued the token — needed so we refresh against
    the correct endpoint (production vs staging vs branch deploys).
    """
    try:
        payload_b64 = access_token.split(".")[1]
        # Fix padding
        padded = payload_b64 + "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        return payload.get("iss")
    except Exception:
        return None


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp
    user_id: str = ""
    email: str = ""
    issuer: str = ""  # e.g. "https://xyz.supabase.co/auth/v1"
    api_key: str = ""  # Supabase anon key — needed for token refresh

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - REFRESH_BUFFER_SECONDS)

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "user_id": self.user_id,
            "email": self.email,
            "issuer": self.issuer,
            "api_key": self.api_key,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TokenSet:
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=float(data.get("expires_at", 0)),
            user_id=data.get("user_id", ""),
            email=data.get("email", ""),
            issuer=data.get("issuer", ""),
            api_key=data.get("api_key", ""),
        )


# ---------------------------------------------------------------------------
# File storage
# ---------------------------------------------------------------------------


def save_tokens(tokens: TokenSet, path: Path | None = None) -> None:
    """Persist tokens to a per-profile credentials file (mode 0600).

    Writes atomically via a temp file so the credentials file is never
    world-readable, even briefly (avoids TOCTOU between write and chmod).
    """
    creds = path or _default_creds_path()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".credentials.", suffix=".tmp")
    try:
        os.chmod(tmp_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(tokens.to_dict(), indent=2))
        os.replace(tmp_path, creds)
    except Exception:
        os.unlink(tmp_path)
        raise
    logger.debug("Tokens saved to %s", creds)


def load_tokens(path: Path | None = None) -> TokenSet | None:
    """Load tokens from a per-profile credentials file."""
    creds = path or _default_creds_path()
    if creds.exists():
        try:
            data = json.loads(creds.read_text())
            return TokenSet.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            logger.warning("Corrupt credentials file at %s", creds)
    return None


def delete_tokens(path: Path | None = None) -> None:
    """Remove stored tokens for a profile."""
    creds = path or _default_creds_path()
    if creds.exists():
        creds.unlink()


def refresh_access_token(tokens: TokenSet) -> TokenSet:
    """Exchange a refresh token for a new token set via Supabase GoTrue.

    Uses the issuer URL and api_key from the stored token set, so the CLI
    never needs to know Supabase coordinates directly.
    """
    if not tokens.issuer or not tokens.api_key:
        raise ValueError(
            "Cannot refresh: missing issuer or api_key in stored credentials. "
            "Please re-authenticate with: deepvista auth login"
        )

    url = f"{tokens.issuer}/token?grant_type=refresh_token"
    resp = httpx.post(
        url,
        json={"refresh_token": tokens.refresh_token},
        headers={
            "apikey": tokens.api_key,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    user = data.get("user", {})
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=time.time() + data.get("expires_in", 3600),
        user_id=user.get("id", ""),
        email=user.get("email", ""),
        issuer=_extract_issuer(data["access_token"]) or tokens.issuer,
        api_key=tokens.api_key,
    )


def get_valid_token(path: Path | None = None) -> TokenSet | None:
    """Load tokens and auto-refresh if expired. Returns None if not authenticated."""
    creds = path or _default_creds_path()
    tokens = load_tokens(creds)
    if tokens is None:
        return None

    if tokens.is_expired and tokens.refresh_token:
        lock_path = creds.with_suffix(".lock")
        with FileLock(str(lock_path), timeout=10):
            # Re-read inside the lock in case a parallel invocation already refreshed.
            tokens = load_tokens(creds) or tokens
            if tokens.is_expired:
                try:
                    tokens = refresh_access_token(tokens)
                    save_tokens(tokens, creds)
                except httpx.HTTPStatusError as e:
                    logger.error("Token refresh failed: HTTP %s", e.response.status_code)
                    return None
                except (httpx.ConnectError, ValueError) as e:
                    logger.error("Token refresh error: %s", e)
                    return None

    return tokens if tokens.access_token else None
