"""KiCad schematic file parser.

Reads a `.kicad_sch` file and produces a :class:`SchematicFile` containing
all connectivity-relevant objects.  Positional information (coordinates,
angles) is stored on the model objects because the net resolver needs it,
but it is never emitted to the JSON output.

Public API
----------
parse_schematic(path: Path) -> SchematicFile
"""

from __future__ import annotations

import math
from pathlib import Path

from kicad_condenser.parser.sexpr import SExpr, atom, find, find_all, parse
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
    SymbolInstance,
    Wire,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _float(value: str) -> float:
    """Safe string-to-float conversion."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _at(node: SExpr) -> tuple[float, float, float]:
    """Extract (x, y, angle) from an (at X Y [ANGLE]) node."""
    at_node = find(node, "at")
    if at_node is None:
        return 0.0, 0.0, 0.0
    x = _float(at_node[1]) if len(at_node) > 1 else 0.0
    y = _float(at_node[2]) if len(at_node) > 2 else 0.0
    angle = _float(at_node[3]) if len(at_node) > 3 else 0.0
    return x, y, angle


def _xy(node: SExpr) -> tuple[float, float]:
    """Extract (x, y) from an (xy X Y) node."""
    return _float(node[1]), _float(node[2])


def _properties(node: SExpr) -> dict[str, str]:
    """Collect all (property KEY VALUE) children of *node* into a dict."""
    result: dict[str, str] = {}
    for prop in find_all(node, "property"):
        if len(prop) >= 3:
            key = prop[1]
            value = prop[2]
            if isinstance(key, str) and isinstance(value, str):
                result[key] = value
    return result


def _bool_token(node: SExpr, key: str) -> bool:
    """Return True/False for a (key yes|no) child of *node*."""
    child = find(node, key)
    if child is None:
        return True
    return len(child) > 1 and child[1] == "yes"


# ---------------------------------------------------------------------------
# Library symbol parsing
# ---------------------------------------------------------------------------

_PIN_TYPE_TOKENS = {
    "input", "output", "bidirectional", "tri_state", "passive",
    "free", "unspecified", "power_in", "power_out",
    "open_collector", "open_emitter", "no_connect",
}

_PIN_STYLE_TOKENS = {
    "line", "inverted", "clock", "inverted_clock", "input_low",
    "clock_low", "output_low", "edge_clock_high", "non_logic",
}


def _parse_lib_pin(pin_node: SExpr) -> LibSymbolPin:
    """Parse a single (pin ELTYPE STYLE (at ...) ...) node."""
    eltype = "unspecified"
    style_seen = False
    for elem in pin_node[1:]:
        if isinstance(elem, str):
            if elem in _PIN_TYPE_TOKENS and eltype == "unspecified":
                eltype = elem
            elif elem in _PIN_STYLE_TOKENS and not style_seen:
                style_seen = True
        elif isinstance(elem, list):
            break  # reached child nodes

    x, y, angle = _at(pin_node)
    name_node = find(pin_node, "name")
    number_node = find(pin_node, "number")
    name = name_node[1] if (name_node and len(name_node) > 1) else ""
    number = number_node[1] if (number_node and len(number_node) > 1) else ""
    return LibSymbolPin(
        number=number,
        name=name,
        electrical_type=eltype,
        x=x,
        y=y,
        angle=angle,
    )


def _parse_lib_symbol(sym_node: SExpr) -> LibSymbol:
    """Parse a top-level (symbol "LIB_ID" ...) node from lib_symbols."""
    lib_id = sym_node[1]

    extends_node = find(sym_node, "extends")
    extends = extends_node[1] if extends_node else None

    # (power global) child indicates this symbol acts as an implicit global label
    power_node = find(sym_node, "power")
    power_global = (
        power_node is not None
        and len(power_node) > 1
        and power_node[1] == "global"
    )

    in_bom = _bool_token(sym_node, "in_bom")
    on_board = _bool_token(sym_node, "on_board")
    props = _properties(sym_node)

    # Pins live inside child (symbol "LIB_ID_UNIT_STYLE" ...) sub-nodes
    pins: dict[int, list[LibSymbolPin]] = {}
    for child in find_all(sym_node, "symbol"):
        # Extract unit index from the child symbol id: "Device:R_1_1" → unit 1
        child_id = child[1] if len(child) > 1 else ""
        unit_idx = _unit_from_id(child_id)
        unit_pins: list[LibSymbolPin] = [
            _parse_lib_pin(p) for p in find_all(child, "pin")
        ]
        if unit_pins:
            pins.setdefault(unit_idx, []).extend(unit_pins)

    # Also collect top-level pins (unit 0 = common to all units)
    top_pins = [_parse_lib_pin(p) for p in find_all(sym_node, "pin")]
    if top_pins:
        pins.setdefault(0, []).extend(top_pins)

    return LibSymbol(
        lib_id=lib_id,
        extends=extends,
        in_bom=in_bom,
        on_board=on_board,
        power_global=power_global,
        properties=props,
        pins=pins,
    )


def _unit_from_id(child_id: str) -> int:
    """Extract the unit number from a symbol unit identifier string.

    KiCad encodes sub-symbols as "LIBNAME_UNIT_STYLE", e.g. "Device:R_1_1".
    The second-to-last underscore-separated token is the unit index.
    Returns 0 if the pattern is not matched.
    """
    parts = child_id.rsplit("_", 2)
    if len(parts) == 3:
        try:
            return int(parts[1])
        except ValueError:
            pass
    return 0


# ---------------------------------------------------------------------------
# Schematic symbol instance parsing
# ---------------------------------------------------------------------------

def _parse_symbol_instance(sym_node: SExpr) -> SchematicSymbol:
    """Parse a schematic-level (symbol (lib_id "LIB_ID") ...) placement node (KiCad 10+)."""
    lib_id_node = find(sym_node, "lib_id")
    lib_id = lib_id_node[1] if lib_id_node else ""
    x, y, angle = _at(sym_node)

    # Mirror flags come from 'mirror' token
    mirror_node = find(sym_node, "mirror")
    mirror_x = False
    mirror_y = False
    if mirror_node:
        for item in mirror_node[1:]:
            if item == "x":
                mirror_x = True
            elif item == "y":
                mirror_y = True

    unit_node = find(sym_node, "unit")
    unit = int(unit_node[1]) if (unit_node and len(unit_node) > 1) else 1

    in_bom_node = find(sym_node, "in_bom")
    in_bom = (in_bom_node[1] == "yes") if (in_bom_node and len(in_bom_node) > 1) else True

    on_board_node = find(sym_node, "on_board")
    on_board = (on_board_node[1] == "yes") if (on_board_node and len(on_board_node) > 1) else True

    uuid_node = find(sym_node, "uuid")
    uuid = uuid_node[1] if (uuid_node and len(uuid_node) > 1) else ""

    props = _properties(sym_node)

    # Pin UUID map: (pin "NUMBER" (uuid "..."))
    pin_uuids: dict[str, str] = {}
    for pin_node in find_all(sym_node, "pin"):
        if len(pin_node) < 2 or not isinstance(pin_node[1], str):
            continue
        pin_number = pin_node[1]
        pu = find(pin_node, "uuid")
        if pu and len(pu) > 1:
            pin_uuids[pin_number] = pu[1]

    # Instance data
    instances: list[SymbolInstance] = []
    instances_node = find(sym_node, "instances")
    if instances_node:
        for project_node in find_all(instances_node, "project"):
            project_name = project_node[1] if len(project_node) > 1 else ""
            for path_node in find_all(project_node, "path"):
                path_str = path_node[1] if len(path_node) > 1 else ""
                ref_node = find(path_node, "reference")
                ref = ref_node[1] if (ref_node and len(ref_node) > 1) else "?"
                inst_unit_node = find(path_node, "unit")
                inst_unit = int(inst_unit_node[1]) if (inst_unit_node and len(inst_unit_node) > 1) else 1
                instances.append(SymbolInstance(
                    project=project_name,
                    path=path_str,
                    reference=ref,
                    unit=inst_unit,
                ))

    return SchematicSymbol(
        lib_id=lib_id,
        unit=unit,
        in_bom=in_bom,
        on_board=on_board,
        uuid=uuid,
        properties=props,
        pin_uuids=pin_uuids,
        instances=instances,
        x=x,
        y=y,
        angle=angle,
        mirror_x=mirror_x,
        mirror_y=mirror_y,
    )


# ---------------------------------------------------------------------------
# Connectivity primitive parsing
# ---------------------------------------------------------------------------

def _parse_wire(wire_node: SExpr) -> Wire:
    pts = find(wire_node, "pts")
    if pts is None:
        return Wire(0.0, 0.0, 0.0, 0.0)
    xys = find_all(pts, "xy")
    if len(xys) < 2:
        return Wire(0.0, 0.0, 0.0, 0.0)
    x1, y1 = _xy(xys[0])
    x2, y2 = _xy(xys[1])
    return Wire(x1, y1, x2, y2)


def _parse_no_connect(nc_node: SExpr) -> NoConnect:
    x, y, _ = _at(nc_node)
    return NoConnect(x, y)


def _parse_junction(junc_node: SExpr) -> Junction:
    x, y, _ = _at(junc_node)
    return Junction(x, y)


def _parse_label(label_node: SExpr) -> Label:
    text = label_node[1] if len(label_node) > 1 else ""
    x, y, _ = _at(label_node)
    return Label(text=text, x=x, y=y)


def _parse_global_label(gl_node: SExpr) -> GlobalLabel:
    text = gl_node[1] if len(gl_node) > 1 else ""
    x, y, _ = _at(gl_node)
    return GlobalLabel(text=text, x=x, y=y)


def _parse_hier_label(hl_node: SExpr) -> HierarchicalLabel:
    text = hl_node[1] if len(hl_node) > 1 else ""
    shape_node = find(hl_node, "shape")
    shape = shape_node[1] if (shape_node and len(shape_node) > 1) else "passive"
    x, y, _ = _at(hl_node)
    return HierarchicalLabel(text=text, shape=shape, x=x, y=y)


def _parse_sheet(sheet_node: SExpr) -> HierarchicalSheet:
    props = _properties(sheet_node)
    sheet_name = props.get("Sheetname", props.get("Sheet name", ""))
    file_name = props.get("Sheetfile", props.get("Sheet file", ""))

    uuid_node = find(sheet_node, "uuid")
    uuid = uuid_node[1] if (uuid_node and len(uuid_node) > 1) else ""

    pins: list[SheetPin] = []
    for pin_node in find_all(sheet_node, "pin"):
        if len(pin_node) < 3:
            continue
        pin_name = pin_node[1]
        pin_type = pin_node[2] if isinstance(pin_node[2], str) else "passive"
        px, py, _ = _at(pin_node)
        pins.append(SheetPin(name=pin_name, electrical_type=pin_type, x=px, y=py))

    return HierarchicalSheet(
        sheet_name=sheet_name,
        file_name=file_name,
        uuid=uuid,
        pins=pins,
    )


# ---------------------------------------------------------------------------
# Top-level parser
# ---------------------------------------------------------------------------

def parse_schematic(path: Path) -> SchematicFile:
    """Parse a KiCad `.kicad_sch` file and return a :class:`SchematicFile`.

    Parameters
    ----------
    path:
        Absolute or relative path to the `.kicad_sch` file.
    """
    text = Path(path).read_text(encoding="utf-8")
    root = parse(text)

    if not isinstance(root, list) or not root or root[0] != "kicad_sch":
        raise ValueError(f"Not a valid KiCad schematic file: {path}")

    version_node = find(root, "version")
    version = int(version_node[1]) if (version_node and len(version_node) > 1) else 0

    uuid_node = find(root, "uuid")
    uuid = uuid_node[1] if (uuid_node and len(uuid_node) > 1) else ""

    # --- Library symbols ---
    lib_symbols: dict[str, LibSymbol] = {}
    lib_sym_section = find(root, "lib_symbols")
    if lib_sym_section:
        for sym_node in find_all(lib_sym_section, "symbol"):
            lib_sym = _parse_lib_symbol(sym_node)
            lib_symbols[lib_sym.lib_id] = lib_sym

    # --- Symbol instances ---
    # KiCad 10+ placed symbols use (symbol (lib_id "...") ...) format.
    # Lib symbol definitions (in lib_symbols section) use a bare string first
    # element and are already parsed above; they won't appear here as find_all
    # only searches direct children of root.
    symbols: list[SchematicSymbol] = []
    for sym_node in find_all(root, "symbol"):
        if find(sym_node, "lib_id") is None:
            continue
        symbols.append(_parse_symbol_instance(sym_node))

    # --- Wires ---
    wires: list[Wire] = [_parse_wire(w) for w in find_all(root, "wire")]

    # --- No connects ---
    no_connects: list[NoConnect] = [
        _parse_no_connect(nc) for nc in find_all(root, "no_connect")
    ]

    # --- Junctions ---
    junctions: list[Junction] = [
        _parse_junction(j) for j in find_all(root, "junction")
    ]

    # --- Local labels ---
    labels: list[Label] = [
        _parse_label(l) for l in find_all(root, "label")
    ]

    # --- Global labels ---
    global_labels: list[GlobalLabel] = [
        _parse_global_label(gl) for gl in find_all(root, "global_label")
    ]

    # --- Hierarchical labels ---
    hier_labels: list[HierarchicalLabel] = [
        _parse_hier_label(hl) for hl in find_all(root, "hierarchical_label")
    ]

    # --- Hierarchical sheets ---
    sheets: list[HierarchicalSheet] = [
        _parse_sheet(s) for s in find_all(root, "sheet")
    ]

    return SchematicFile(
        uuid=uuid,
        version=version,
        lib_symbols=lib_symbols,
        symbols=symbols,
        wires=wires,
        no_connects=no_connects,
        junctions=junctions,
        labels=labels,
        global_labels=global_labels,
        hier_labels=hier_labels,
        sheets=sheets,
    )
