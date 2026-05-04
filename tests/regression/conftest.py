"""Regression test fixtures and helpers."""

import json
from pathlib import Path

import pytest

from kicad_condenser.netlist.resolver import resolve
from kicad_condenser.serializer.json_output import serialize

SCHEMATICS_DIR = Path(__file__).parent / "schematics"


def run_pipeline(sch_path: Path) -> dict:
    """Run the full condenser pipeline on *sch_path* and return the output dict."""
    netlist = resolve(sch_path)
    return serialize(netlist)


def pytest_generate_tests(metafunc):
    """Parametrize over all schematic directories that contain an expected.json."""
    if "schematic_dir" in metafunc.fixturenames:
        dirs = [
            d for d in sorted(SCHEMATICS_DIR.iterdir())
            if d.is_dir() and (d / "expected.json").exists()
        ]
        metafunc.parametrize("schematic_dir", dirs, ids=[d.name for d in dirs])
