"""Raw KiCad schematic data models.

These dataclasses represent the parsed content of a `.kicad_sch` file
closely matching the KiCad S-expression structure.  Positional information
(coordinates, angles) is stored here because the net resolver needs it, but
it is *never* emitted to the final JSON output.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Library symbol definitions (embedded in the schematic's lib_symbols section)
# ---------------------------------------------------------------------------

@dataclass
class LibSymbolPin:
    number: str          # e.g. "1", "A1"
    name: str            # e.g. "VCC", "~"
    electrical_type: str # input / output / passive / power_in / …
    # Positional — used for net resolution, not serialised
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0


@dataclass
class LibSymbol:
    """A symbol definition embedded in the schematic's lib_symbols section."""
    lib_id: str          # e.g. "Device:R"
    extends: str | None  # parent symbol id if this is a derived symbol
    in_bom: bool = True
    on_board: bool = True
    properties: dict[str, str] = field(default_factory=dict)
    # Pins keyed by unit index (0 = common to all units)
    pins: dict[int, list[LibSymbolPin]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Schematic symbol instances
# ---------------------------------------------------------------------------

@dataclass
class SymbolInstance:
    """Per-project / per-path instance data for a schematic symbol."""
    project: str
    path: str     # UUID path, e.g. "/sheetUUID"
    reference: str
    unit: int


@dataclass
class SchematicSymbol:
    """An instance of a library symbol placed on a schematic sheet."""
    lib_id: str          # references a key in SchematicFile.lib_symbols
    unit: int
    in_bom: bool
    on_board: bool
    uuid: str
    properties: dict[str, str] = field(default_factory=dict)
    # pin uuid map: pin_number -> uuid (from the schematic file's pin tokens)
    pin_uuids: dict[str, str] = field(default_factory=dict)
    instances: list[SymbolInstance] = field(default_factory=list)
    # Positional — used for net resolution, not serialised
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0
    mirror_x: bool = False
    mirror_y: bool = False

    @property
    def reference(self) -> str:
        """Best-effort reference from the first instance, or from properties."""
        if self.instances:
            return self.instances[0].reference
        return self.properties.get("Reference", "?")

    @property
    def value(self) -> str:
        return self.properties.get("Value", "")

    @property
    def footprint(self) -> str:
        return self.properties.get("Footprint", "")

    @property
    def datasheet(self) -> str:
        return self.properties.get("Datasheet", "")


# ---------------------------------------------------------------------------
# Connectivity primitives (wires, labels)
# ---------------------------------------------------------------------------

@dataclass
class Wire:
    """A wire segment on a schematic sheet."""
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class NoConnect:
    """A no-connect marker placed on a pin."""
    x: float
    y: float


@dataclass
class Junction:
    """A junction dot where three or more wires meet."""
    x: float
    y: float


@dataclass
class Label:
    """A local net label (scoped to the current sheet)."""
    text: str
    x: float
    y: float


@dataclass
class GlobalLabel:
    """A global net label (visible across all sheets)."""
    text: str
    x: float
    y: float


@dataclass
class HierarchicalLabel:
    """A hierarchical label — connects to a parent sheet's SheetPin."""
    text: str
    shape: str  # input / output / bidirectional / tri_state / passive
    x: float
    y: float


@dataclass
class SheetPin:
    """A pin on a hierarchical sheet box in the *parent* schematic."""
    name: str
    electrical_type: str
    x: float
    y: float


@dataclass
class HierarchicalSheet:
    """A sub-sheet reference placed on a schematic."""
    sheet_name: str
    file_name: str   # relative path to the sub-schematic .kicad_sch
    uuid: str
    pins: list[SheetPin] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level schematic file
# ---------------------------------------------------------------------------

@dataclass
class SchematicFile:
    """Complete parsed content of a single `.kicad_sch` file."""
    uuid: str
    version: int
    lib_symbols: dict[str, LibSymbol] = field(default_factory=dict)
    symbols: list[SchematicSymbol] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    no_connects: list[NoConnect] = field(default_factory=list)
    junctions: list[Junction] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    global_labels: list[GlobalLabel] = field(default_factory=list)
    hier_labels: list[HierarchicalLabel] = field(default_factory=list)
    sheets: list[HierarchicalSheet] = field(default_factory=list)
