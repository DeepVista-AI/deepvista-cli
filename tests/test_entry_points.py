"""Regression tests for the CLI console-script entry points.

`deepvista` is the canonical command; `dv` is a short alias (DV-1324). Both must
stay mapped to the same callable so the two commands remain interchangeable.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

TARGET = "deepvista_cli.main:cli"
PROJECT = "project"
SCRIPTS = "scripts"
DEEPVISTA = "deepvista"
DV = "dv"


def _scripts() -> dict:
    data = tomllib.loads(PYPROJECT.read_text())
    return data[PROJECT][SCRIPTS]


def test_both_entry_points_registered() -> None:
    scripts = _scripts()
    assert DEEPVISTA in scripts, "canonical `deepvista` entry point is missing"
    assert DV in scripts, "`dv` alias entry point is missing"


def test_alias_points_to_same_target() -> None:
    scripts = _scripts()
    assert scripts[DEEPVISTA] == TARGET
    assert scripts[DV] == scripts[DEEPVISTA], "`dv` must alias the same callable as `deepvista`"
