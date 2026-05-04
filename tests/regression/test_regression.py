"""Regression tests — compare pipeline output against expected.json fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.regression.conftest import run_pipeline


def _find_root_sch(schematic_dir: Path) -> Path:
    """Return the root .kicad_sch in *schematic_dir*.

    Prefers a file whose stem matches the directory name, then the first found.
    """
    preferred = schematic_dir / f"{schematic_dir.name}.kicad_sch"
    if preferred.exists():
        return preferred
    candidates = sorted(schematic_dir.glob("*.kicad_sch"))
    if candidates:
        return candidates[0]
    pytest.fail(f"No .kicad_sch found in {schematic_dir}")


class TestRegressionSchematics:
    def test_output_matches_expected(self, schematic_dir: Path):
        expected_path = schematic_dir / "expected.json"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))

        root_sch = _find_root_sch(schematic_dir)
        actual = run_pipeline(root_sch)

        # Normalize both dicts for comparison: sort lists by a stable key
        _normalize(actual)
        _normalize(expected)

        assert actual == expected, (
            f"Output for '{schematic_dir.name}' does not match expected.json.\n"
            f"Expected:\n{json.dumps(expected, indent=2)}\n\n"
            f"Actual:\n{json.dumps(actual, indent=2)}"
        )

    def test_no_positional_fields_in_output(self, schematic_dir: Path):
        root_sch = _find_root_sch(schematic_dir)
        actual = run_pipeline(root_sch)
        _assert_no_positional(actual)


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def _normalize(obj):
    """Sort lists within the output dict by stable keys for deterministic comparison."""
    if isinstance(obj, dict):
        for v in obj.values():
            _normalize(v)
    elif isinstance(obj, list):
        for item in obj:
            _normalize(item)
        # Sort lists of dicts by their first string value
        if obj and all(isinstance(i, dict) for i in obj):
            obj.sort(key=_sort_key)


def _sort_key(d: dict):
    if "reference" in d:
        return ("reference", d["reference"])
    if "name" in d:
        return ("name", d["name"])
    if "number" in d:
        return ("number", d["number"])
    if "pin" in d:
        return ("pin", d["pin"])
    return ("", str(d))


def _assert_no_positional(obj, path: str = ""):
    positional_keys = {"x", "y", "at", "angle", "xy", "position"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in positional_keys, (
                f"Positional key '{k}' found in output at path '{path}.{k}'"
            )
            _assert_no_positional(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_positional(item, f"{path}[{i}]")
