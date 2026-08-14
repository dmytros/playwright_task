from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing config file: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config {path} must be a mapping")
    return data


def load_parsing_config() -> dict[str, Any]:
    return _load_yaml("parsing.yaml")


def load_scoring_config() -> dict[str, Any]:
    return _load_yaml("scoring.yaml")


def load_runtime_config() -> dict[str, Any]:
    return _load_yaml("runtime.yaml")
