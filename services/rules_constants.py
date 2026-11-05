"""Read numbers from rules_constants.yaml by rule ID. Never hard-code them from prose."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "rules_constants.yaml"


@lru_cache
def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must hold a mapping")
    return loaded


def rule_constants(rule_id: str, path: Path = DEFAULT_PATH) -> dict[str, Any]:
    section = _load(path).get(rule_id)
    if not isinstance(section, dict):
        raise KeyError(f"{rule_id} is not in {path.name}")
    return section
