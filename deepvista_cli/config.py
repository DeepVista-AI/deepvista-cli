"""Configuration management for the DeepVista CLI.

Resolution order for each setting:
  1. CLI flags (--api-url, --format, etc.)
  2. Config file (~/.config/deepvista/config.json) profile
  3. Built-in defaults
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_API_URL = "https://api.deepvista.ai"
DEFAULT_AUTH_URL = "https://app.deepvista.ai"
DEFAULT_FORMAT = "json"
CONFIG_DIR = Path(os.environ.get("DEEPVISTA_CONFIG_DIR", Path.home() / ".config" / "deepvista"))


def credentials_path(profile: str = "default") -> Path:
    """Return the credentials file path for a given profile.

    Each profile gets its own file so staging and production tokens
    never overwrite each other:
      default  -> ~/.config/deepvista/credentials.default.json
      staging  -> ~/.config/deepvista/credentials.staging.json
    """
    return CONFIG_DIR / f"credentials.{profile}.json"


PROFILES_PATH = CONFIG_DIR / "config.json"


# ---------------------------------------------------------------------------
# Exit codes (following GWS pattern)
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_AUTH_ERROR = 2
EXIT_VALIDATION_ERROR = 3
EXIT_NETWORK_ERROR = 4
EXIT_INTERNAL_ERROR = 5


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------


def _load_profiles() -> dict:
    """Load profiles from ~/.config/deepvista/config.json."""
    if PROFILES_PATH.exists():
        try:
            return json.loads(PROFILES_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_profiles(profiles: dict) -> None:
    """Save profiles to ~/.config/deepvista/config.json (mode 0600 — contains API keys)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_PATH.write_text(json.dumps(profiles, indent=2))
    PROFILES_PATH.chmod(0o600)


def get_profile(name: str) -> dict:
    """Get a named profile. Returns empty dict if not found."""
    return _load_profiles().get(name, {})


def set_profile(name: str, settings: dict) -> None:
    """Create or update a named profile."""
    profiles = _load_profiles()
    profiles[name] = settings
    _save_profiles(profiles)


def list_profiles() -> dict:
    """List all profiles."""
    return _load_profiles()


def delete_profile(name: str) -> bool:
    """Delete a named profile. Returns True if it existed."""
    profiles = _load_profiles()
    if name in profiles:
        del profiles[name]
        _save_profiles(profiles)
        return True
    return False


# ---------------------------------------------------------------------------
# Runtime config — resolved once per invocation
# ---------------------------------------------------------------------------


@dataclass
class CLIConfig:
    """Resolved configuration for a single CLI invocation."""

    api_url: str = DEFAULT_API_URL
    auth_url: str = DEFAULT_AUTH_URL
    output_format: str = DEFAULT_FORMAT
    verbose: bool = False
    dry_run: bool = False
    profile: str = "default"

    def apply_profile(self, profile_name: str) -> None:
        """Apply settings from a named profile."""
        profile = get_profile(profile_name)
        if not profile:
            return

        if "api_url" in profile:
            self.api_url = profile["api_url"]
        if "auth_url" in profile:
            self.auth_url = profile["auth_url"]

    def ensure_config_dir(self) -> Path:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        return CONFIG_DIR
