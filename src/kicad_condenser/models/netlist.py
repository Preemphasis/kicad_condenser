"""Resolved netlist data models.

These are the *output* models — all positional information has been stripped.
They represent the electrical connectivity extracted from one or more schematic
sheets after full net resolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResolvedPin:
    """A single pin on a component with its resolved net name."""
    number: str           # pin number, e.g. "1"
    name: str             # pin name, e.g. "VCC"
    electrical_type: str  # KiCad pin type, e.g. "passive"
    net: str | None       # resolved net name; None = floating; "__NC__" = no-connect marker


@dataclass
class Component:
    """A fully resolved schematic component (all units merged)."""
    reference: str
    value: str
    footprint: str
    datasheet: str
    properties: dict[str, str]
    pins: list[ResolvedPin] = field(default_factory=list)


@dataclass
class Net:
    """A named electrical net and all the pins connected to it."""

    @dataclass
    class PinRef:
        reference: str
        pin: str   # pin number

    name: str
    pins: list[PinRef] = field(default_factory=list)


@dataclass
class Netlist:
    """Complete condensed netlist for a KiCad project."""
    project: str
    components: list[Component] = field(default_factory=list)
    nets: list[Net] = field(default_factory=list)
