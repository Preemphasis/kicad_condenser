"""Net resolver — builds a fully resolved :class:`Netlist` from parsed schematic files.

Algorithm overview
------------------
1. **Wire graph per sheet**: collect all wire-segment endpoints, Union-Find
   connects them into components ("net candidates").
2. **Label assignment**: each local/global/hierarchical label is attached to
   the component whose wire endpoint is at (or very close to) the label
   position.
3. **No-connect markers**: any component with a no-connect at its position gets
   the synthetic net name ``__NC__``.
4. **Hierarchical propagation**: a ``SheetPin`` in the parent sheet is at some
   position → belongs to a component.  The corresponding sub-schematic's
   ``HierarchicalLabel`` (same name) also belongs to a component in the
   sub-sheet.  The two components are merged into one net.
5. **Global label propagation**: ``GlobalLabel`` objects with the same text
   across all sheets share one net name.
6. **Pin-to-net assignment**: for every placed ``SchematicSymbol`` each library
   pin's position is transformed to sheet-absolute coordinates (rotate + offset
   by symbol origin).  The nearest wire component is looked up; the pin records
   that net name.
7. **Netlist assembly**: components are grouped by reference designator (multi-
   unit symbols are merged), and a ``Net`` object is built for every distinct
   net name.

Public API
----------
resolve(root_path: Path) -> Netlist
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

from kicad_condenser.models.netlist import Component, Net, Netlist, ResolvedPin
from kicad_condenser.models.schematic import (
    GlobalLabel,
    HierarchicalLabel,
    HierarchicalSheet,
    Junction,
    Label,
    LibSymbol,
    LibSymbolPin,
    NoConnect,
    SchematicFile,
    SchematicSymbol,
    SheetPin,
    Wire,
)
from kicad_condenser.parser.schematic import parse_schematic

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# KiCad schematic coordinates have 4-decimal precision (0.0001 mm)
_SNAP = 1e-3   # snap tolerance in mm — wires within 1 µm are considered coincident


# ---------------------------------------------------------------------------
# Union-Find (disjoint set) data structure
# ---------------------------------------------------------------------------

class _UF:
    """Path-compressed Union-Find."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def add(self, x: int) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path halving
            x = self._parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1


# ---------------------------------------------------------------------------
# Coordinate snapping
# ---------------------------------------------------------------------------

def _snap(v: float) -> float:
    """Round to _SNAP grid to avoid floating-point comparison noise."""
    return round(v / _SNAP) * _SNAP


def _snap_xy(x: float, y: float) -> tuple[float, float]:
    return _snap(x), _snap(y)


# ---------------------------------------------------------------------------
# Per-sheet wire graph
# ---------------------------------------------------------------------------

class _SheetGraph:
    """Wire connectivity graph for one schematic sheet."""

    def __init__(self) -> None:
        self._uf = _UF()
        # Map from snapped (x, y) → integer node id
        self._node_id: dict[tuple[float, float], int] = {}
        self._next_id = 0
        # Net name assigned to each root component
        self._net_names: dict[int, str] = {}

    def _node(self, x: float, y: float) -> int:
        key = _snap_xy(x, y)
        if key not in self._node_id:
            nid = self._next_id
            self._next_id += 1
            self._node_id[key] = nid
            self._uf.add(nid)
        return self._node_id[key]

    def add_wire(self, wire: Wire) -> None:
        a = self._node(wire.x1, wire.y1)
        b = self._node(wire.x2, wire.y2)
        self._uf.union(a, b)

    def add_junction(self, j: Junction) -> None:
        # Junctions by themselves just ensure the point exists as a node
        self._node(j.x, j.y)

    def component_of(self, x: float, y: float) -> int | None:
        """Return the root component id for the point nearest to (x, y).

        Returns None if no wire endpoint is within snap distance.
        """
        key = _snap_xy(x, y)
        nid = self._node_id.get(key)
        if nid is None:
            return None
        return self._uf.find(nid)

    def get_or_create_component(self, x: float, y: float) -> int:
        """Like component_of but always creates a node (for isolated labels)."""
        nid = self._node(x, y)
        return self._uf.find(nid)

    def assign_name(self, component: int, name: str) -> None:
        """Assign a net name to a component.  Existing names are not overwritten
        unless the new name is a 'stronger' label (global > local > anonymous)."""
        existing = self._net_names.get(component)
        if existing is None:
            self._net_names[component] = name
        # Global labels (prefixed __GLOBAL__) take priority over local ones
        elif existing.startswith("__GLOBAL__") or not name.startswith("__GLOBAL__"):
            pass  # keep existing
        else:
            self._net_names[component] = name

    def net_name(self, component: int) -> str | None:
        return self._net_names.get(component)

    def merge_components(self, comp_a: int, comp_b: int) -> None:
        """Union two components, preserving the net name if one side has it."""
        name_a = self._net_names.pop(comp_a, None)
        name_b = self._net_names.pop(comp_b, None)
        self._uf.union(comp_a, comp_b)
        new_root = self._uf.find(comp_a)
        winner = name_a or name_b
        if winner:
            self._net_names[new_root] = winner

    def all_components(self) -> set[int]:
        return {self._uf.find(nid) for nid in self._uf._parent}


# ---------------------------------------------------------------------------
# Pin position transformation
# ---------------------------------------------------------------------------

def _rotate(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Rotate (x, y) by angle_deg counter-clockwise (KiCad convention)."""
    if angle_deg == 0.0:
        return x, y
    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def _pin_absolute_position(
    sym: SchematicSymbol,
    pin: LibSymbolPin,
) -> tuple[float, float]:
    """Compute the sheet-absolute position of a library pin for a placed symbol.

    KiCad transformation order:
      1. Mirror (x or y) the pin's local coordinates
      2. Rotate by the symbol's angle
      3. Translate by the symbol's origin
    """
    px, py = pin.x, pin.y

    # Apply mirror
    if sym.mirror_x:
        py = -py
    if sym.mirror_y:
        px = -px

    # Rotate
    px, py = _rotate(px, py, sym.angle)

    # Translate
    return px + sym.x, py + sym.y


# ---------------------------------------------------------------------------
# Sheet-level graph builder
# ---------------------------------------------------------------------------

def _build_sheet_graph(sch: SchematicFile) -> _SheetGraph:
    graph = _SheetGraph()

    for wire in sch.wires:
        graph.add_wire(wire)

    for j in sch.junctions:
        graph.add_junction(j)

    # Local labels
    for label in sch.labels:
        comp = graph.get_or_create_component(label.x, label.y)
        root = graph._uf.find(comp)
        graph.assign_name(root, label.text)

    # Global labels — use a special prefix so they propagate cross-sheet
    for gl in sch.global_labels:
        comp = graph.get_or_create_component(gl.x, gl.y)
        root = graph._uf.find(comp)
        graph.assign_name(root, f"__GLOBAL__{gl.text}")

    # Hierarchical labels — the name is the same as the SheetPin name that
    # connects to them from the parent sheet.  We assign it as-is so the
    # parent sheet can look it up.
    for hl in sch.hier_labels:
        comp = graph.get_or_create_component(hl.x, hl.y)
        root = graph._uf.find(comp)
        graph.assign_name(root, hl.text)

    # Power global symbols — a lib symbol marked (power global) acts as an
    # implicit global label whose net name is the placed symbol's Value.
    # There is no explicit wire; the pin position IS the connection point.
    for sym in sch.symbols:
        lib_sym = sch.lib_symbols.get(sym.lib_id)
        if lib_sym is None or not lib_sym.power_global:
            continue
        net_name = sym.value
        # Collect pins for this unit (unit 0 = common to all units)
        power_pins = list(lib_sym.pins.get(0, []))
        if sym.unit != 0:
            power_pins.extend(lib_sym.pins.get(sym.unit, []))
        for pin_def in power_pins:
            abs_x, abs_y = _pin_absolute_position(sym, pin_def)
            comp = graph.get_or_create_component(abs_x, abs_y)
            graph.assign_name(graph._uf.find(comp), f"__GLOBAL__{net_name}")

    return graph


# ---------------------------------------------------------------------------
# Resolver state
# ---------------------------------------------------------------------------

class _Resolver:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        # Keyed by schematic UUID
        self._graphs: dict[str, _SheetGraph] = {}
        self._schematics: dict[str, SchematicFile] = {}

    def _load(self, path: Path) -> SchematicFile:
        sch = parse_schematic(path)
        if sch.uuid not in self._schematics:
            self._schematics[sch.uuid] = sch
            self._graphs[sch.uuid] = _build_sheet_graph(sch)
            # Recurse into sub-sheets
            for sheet in sch.sheets:
                sub_path = path.parent / sheet.file_name
                if sub_path.exists():
                    self._load(sub_path)
        return sch

    def _propagate_hierarchical(self) -> None:
        """Merge net components across hierarchical sheet boundaries."""
        for parent_uuid, parent_sch in self._schematics.items():
            parent_graph = self._graphs[parent_uuid]
            for sheet in parent_sch.sheets:
                # Find the sub-schematic
                sub_sch = self._find_sub_sch(sheet.file_name, parent_sch)
                if sub_sch is None:
                    continue
                sub_graph = self._graphs[sub_sch.uuid]

                # For each SheetPin in the parent, find the matching
                # HierarchicalLabel in the sub-schematic and merge components.
                for sp in sheet.pins:
                    parent_comp = parent_graph.component_of(sp.x, sp.y)
                    if parent_comp is None:
                        parent_comp = parent_graph.get_or_create_component(sp.x, sp.y)

                    # Find matching hierarchical label in sub-schematic
                    for hl in sub_sch.hier_labels:
                        if hl.text == sp.name:
                            sub_comp = sub_graph.component_of(hl.x, hl.y)
                            if sub_comp is None:
                                sub_comp = sub_graph.get_or_create_component(hl.x, hl.y)

                            # Propagate the net name downward
                            parent_name = parent_graph.net_name(parent_comp)
                            sub_name = sub_graph.net_name(sub_comp)
                            canonical = parent_name or sub_name or sp.name

                            parent_graph.assign_name(parent_comp, canonical)
                            sub_graph.assign_name(sub_comp, canonical)
                            break

    def _find_sub_sch(self, file_name: str, parent: SchematicFile) -> SchematicFile | None:
        """Locate a loaded sub-schematic by its file name."""
        # Find path from any loaded schematic
        for sch in self._schematics.values():
            pass  # we don't store paths — resolve by file_name relative to root
        # Try root_dir first, then any sub-directory
        candidate = self._root_dir / file_name
        if candidate.exists():
            sub_sch = parse_schematic(candidate)
            return self._schematics.get(sub_sch.uuid)
        return None

    def _propagate_globals(self) -> None:
        """Ensure all GlobalLabel components with the same text share a name."""
        # Collect all global label texts — from explicit global_label nodes and
        # from power global symbols (which act as implicit global labels).
        global_texts: set[str] = set()
        for sch in self._schematics.values():
            for gl in sch.global_labels:
                global_texts.add(gl.text)
            for sym in sch.symbols:
                lib_sym = sch.lib_symbols.get(sym.lib_id)
                if lib_sym is not None and lib_sym.power_global:
                    global_texts.add(sym.value)

        for text in global_texts:
            # Assign the clean name (strip prefix) to all components with __GLOBAL__ prefix
            clean = text
            for uuid, graph in self._graphs.items():
                for comp in graph.all_components():
                    name = graph.net_name(comp)
                    if name == f"__GLOBAL__{text}":
                        graph._net_names[comp] = clean

    def _assign_no_connects(self) -> None:
        """Mark isolated no-connect positions with the synthetic __NC__ name."""
        for uuid, sch in self._schematics.items():
            graph = self._graphs[uuid]
            for nc in sch.no_connects:
                comp = graph.get_or_create_component(nc.x, nc.y)
                root = graph._uf.find(comp)
                if graph.net_name(root) is None:
                    graph.assign_name(root, "__NC__")

    def resolve(self, root_path: Path) -> Netlist:
        root_sch = self._load(root_path)
        self._propagate_hierarchical()
        self._propagate_globals()
        self._assign_no_connects()

        # --- Assign anonymous net names to unnamed components ---
        _anon_counter = [0]

        def _get_or_anon(graph: _SheetGraph, comp: int) -> str | None:
            name = graph.net_name(comp)
            if name is None:
                # Anonymous net — leave as None (floating)
                pass
            return name

        # --- Build component table ---
        # reference → {pin_number → ResolvedPin}
        comp_pins: dict[str, dict[str, ResolvedPin]] = defaultdict(dict)
        comp_meta: dict[str, tuple[str, str, str, dict]] = {}  # ref → (value, fp, ds, props)

        for uuid, sch in self._schematics.items():
            graph = self._graphs[uuid]
            for sym in sch.symbols:
                if not sym.in_bom:
                    continue
                ref = sym.reference
                if ref in ("?", ""):
                    continue

                # Metadata (last unit seen wins; all units should have the same)
                comp_meta[ref] = (sym.value, sym.footprint, sym.datasheet, dict(sym.properties))

                # Library symbol lookup
                lib_sym = sch.lib_symbols.get(sym.lib_id)
                if lib_sym is None:
                    continue

                # Resolve pins for this unit
                pin_defs = self._get_pins_for_unit(lib_sym, sym.unit)
                for pin_def in pin_defs:
                    abs_x, abs_y = _pin_absolute_position(sym, pin_def)
                    comp = graph.component_of(abs_x, abs_y)
                    if comp is None:
                        # Pin endpoint not on any wire — check for direct label
                        comp = graph.get_or_create_component(abs_x, abs_y)
                    net = _get_or_anon(graph, comp)
                    comp_pins[ref][pin_def.number] = ResolvedPin(
                        number=pin_def.number,
                        name=pin_def.name,
                        electrical_type=pin_def.electrical_type,
                        net=net,
                    )

        # --- Assemble output models ---
        components: list[Component] = []
        net_map: dict[str, list[Net.PinRef]] = defaultdict(list)

        for ref in sorted(comp_pins.keys()):
            meta = comp_meta.get(ref, ("", "", "", {}))
            value, footprint, datasheet, properties = meta
            # Remove internal KiCad properties that are redundant
            clean_props = {
                k: v for k, v in properties.items()
                if k not in ("Reference", "Value", "Footprint", "Datasheet")
            }
            pins = sorted(comp_pins[ref].values(), key=lambda p: p.number)
            components.append(Component(
                reference=ref,
                value=value,
                footprint=footprint,
                datasheet=datasheet,
                properties=clean_props,
                pins=pins,
            ))
            for pin in pins:
                if pin.net and pin.net != "__NC__":
                    net_map[pin.net].append(Net.PinRef(reference=ref, pin=pin.number))

        nets: list[Net] = [
            Net(name=name, pins=sorted(pins, key=lambda p: (p.reference, p.pin)))
            for name, pins in sorted(net_map.items())
        ]

        project_name = root_path.stem
        return Netlist(project=project_name, components=components, nets=nets)

    @staticmethod
    def _get_pins_for_unit(lib_sym: LibSymbol, unit: int) -> list[LibSymbolPin]:
        """Return pins for a specific unit, merging in unit-0 (common) pins."""
        result: list[LibSymbolPin] = []
        # Unit 0 = common to all units
        result.extend(lib_sym.pins.get(0, []))
        if unit != 0:
            result.extend(lib_sym.pins.get(unit, []))
        return result


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def resolve(root_path: Path) -> Netlist:
    """Parse all schematics reachable from *root_path* and return a resolved
    :class:`Netlist`.

    Parameters
    ----------
    root_path:
        Path to the root `.kicad_sch` file.
    """
    root_path = Path(root_path).resolve()
    resolver = _Resolver(root_dir=root_path.parent)
    return resolver.resolve(root_path)
