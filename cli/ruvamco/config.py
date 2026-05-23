"""
RUVAMCO CLI — Configuration management.

Handles loading configuration from environment variables, config
files (~/.ruvamco/config.yaml), and CLI flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

CONFIG_DIR = Path.home() / ".ruvamco"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
TOKEN_FILE = CONFIG_DIR / "token"


@dataclass
class RuvamcoConfig:
    """CLI configuration."""

    api_endpoint: str = "https://broker.ruvamco.io/v2"
    api_key: str = ""
    default_plan: str = "developer"
    output_format: str = "table"  # table | json | yaml
    timeout: int = 30

    @classmethod
    def load(cls) -> "RuvamcoConfig":
        """Load config from file, then overlay environment variables."""
        config = cls()

        # Load from file
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = yaml.safe_load(f) or {}
            config.api_endpoint = data.get("api_endpoint", config.api_endpoint)
            config.api_key = data.get("api_key", config.api_key)
            config.default_plan = data.get("default_plan", config.default_plan)
            config.output_format = data.get("output_format", config.output_format)
            config.timeout = data.get("timeout", config.timeout)

        # Environment overrides
        config.api_endpoint = os.environ.get("RUVAMCO_API", config.api_endpoint)
        config.api_key = os.environ.get("RUVAMCO_API_KEY", config.api_key)

        return config

    def save(self) -> None:
        """Persist config to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "api_endpoint": self.api_endpoint,
            "api_key": self.api_key,
            "default_plan": self.default_plan,
            "output_format": self.output_format,
            "timeout": self.timeout,
        }
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    def get_token(self) -> str:
        """Read token from file or environment."""
        if os.environ.get("RUVAMCO_TOKEN"):
            return os.environ["RUVAMCO_TOKEN"]
        if TOKEN_FILE.exists():
            return TOKEN_FILE.read_text().strip()
        return ""

    def set_token(self, token: str) -> None:
        """Persist token to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(token)
        TOKEN_FILE.chmod(0o600)
