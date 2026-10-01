"""Paths and config loading. AFFIX_HOME overrides the repo root (used by tests)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml


def root() -> Path:
    return Path(os.environ.get("AFFIX_HOME", Path(__file__).resolve().parent.parent))


def state_dir() -> Path:
    return root() / "state"


def config_dir() -> Path:
    return root() / "config"


def load_yaml(name: str) -> dict:
    with open(config_dir() / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def settings() -> dict:
    return load_yaml("settings.yaml")


def load_env() -> None:
    """Load .env if python-dotenv is installed; otherwise rely on the real environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(root() / ".env")


def kill_switch_active() -> bool:
    """True if outbound email must halt (spec §11)."""
    if (state_dir() / "KILL").exists():
        return True
    return not settings().get("sending", {}).get("sending_enabled", False)
