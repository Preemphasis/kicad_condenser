"""Unit tests for the schematic file parser."""

import textwrap

import pytest

from kicad_condenser.parser.schematic import parse_schematic
from kicad_condenser.models.schematic import (
    GlobalLabel,
    HierarchicalLabel,
    HierarchicalSheet,
    Label,
    LibSymbol,
    NoConnect,
    SchematicFile,
    SchematicSymbol,
    Wire,
)


# ---------------------------------------------------------------------------
# Minimal schematic fixtures
# ---------------------------------------------------------------------------

MINIMAL_SCH = textwrap.dedent("""\
(kicad_sch
  (version 20231120)
  (generator kicad_condenser_test)
  (uuid "aaaaaaaa-0000-0000-0000-000000000001")

  (lib_symbols
    (symbol "Device:R"
      (pin_numbers hide)
      (pin_names (offset 0))
      (in_bom yes)
      (on_board yes)
      (property "Reference" "R" (id 0) (at 0 0 0))
      (property "Value" "R" (id 1) (at 0 0 0))
      (property "Footprint" "" (id 2) (at 0 0 0))
      (property "Datasheet" "~" (id 3) (at 0 0 0))
      (symbol "R_0_1"
      )
      (symbol "R_1_1"
        (pin passive line (at 0 1.016 270) (length 0)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
        (pin passive line (at 0 -1.016 90) (length 0)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "2" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )

  (symbol "Device:R" (at 10 10 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "bbbbbbbb-0000-0000-0000-000000000001")
    (property "Reference" "R1" (id 0) (at 10 10 0))
    (property "Value" "10k" (id 1) (at 10 10 0))
    (property "Footprint" "Resistor_SMD:R_0402" (id 2) (at 10 10 0))
    (property "Datasheet" "~" (id 3) (at 10 10 0))
    (instances
      (project "test"
        (path "/aaaaaaaa-0000-0000-0000-000000000001"
          (reference "R1")
          (unit 1)
        )
      )
    )
  )

  (wire (pts (xy 10 9.994) (xy 10 5)))
  (wire (pts (xy 10 11.026) (xy 10 15)))

  (label "VCC" (at 10 5 0))
  (label "GND" (at 10 15 0))
)
""")


GLOBAL_LABEL_SCH = textwrap.dedent("""\
(kicad_sch
  (version 20231120)
  (generator kicad_condenser_test)
  (uuid "cccccccc-0000-0000-0000-000000000001")
  (global_label "UART_TX" (shape output) (at 50 20 0))
  (no_connect (at 20 30 0) (uuid "dddddddd-0000-0000-0000-000000000001"))
)
""")


def _parse_text(text: str, tmp_path) -> SchematicFile:
    """Write *text* to a temp file and parse it."""
    path = tmp_path / "test.kicad_sch"
    path.write_text(text, encoding="utf-8")
    return parse_schematic(path)


class TestHeaderParsing:
    def test_version(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert sch.version == 20231120

    def test_uuid(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert sch.uuid == "aaaaaaaa-0000-0000-0000-000000000001"


class TestLibSymbolParsing:
    def test_lib_symbol_registered(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert "Device:R" in sch.lib_symbols

    def test_lib_symbol_properties(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.lib_symbols["Device:R"]
        assert sym.in_bom is True
        assert sym.on_board is True

    def test_lib_symbol_pins_extracted(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.lib_symbols["Device:R"]
        # Pins are in unit 1
        assert 1 in sym.pins
        pins = sym.pins[1]
        assert len(pins) == 2
        pin_numbers = {p.number for p in pins}
        assert pin_numbers == {"1", "2"}

    def test_lib_symbol_pin_electrical_type(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.lib_symbols["Device:R"]
        for pin in sym.pins[1]:
            assert pin.electrical_type == "passive"


class TestSymbolInstanceParsing:
    def test_symbol_count(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert len(sch.symbols) == 1

    def test_symbol_lib_id(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.symbols[0]
        assert sym.lib_id == "Device:R"

    def test_symbol_position(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.symbols[0]
        assert sym.x == pytest.approx(10.0)
        assert sym.y == pytest.approx(10.0)

    def test_symbol_properties(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.symbols[0]
        assert sym.value == "10k"
        assert sym.footprint == "Resistor_SMD:R_0402"

    def test_symbol_reference_from_instance(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.symbols[0]
        assert sym.reference == "R1"

    def test_symbol_uuid(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        sym = sch.symbols[0]
        assert sym.uuid == "bbbbbbbb-0000-0000-0000-000000000001"


class TestWireParsing:
    def test_wire_count(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert len(sch.wires) == 2

    def test_wire_coordinates(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        w = sch.wires[0]
        assert w.x1 == pytest.approx(10.0)
        assert w.y1 == pytest.approx(9.994)
        assert w.x2 == pytest.approx(10.0)
        assert w.y2 == pytest.approx(5.0)


class TestLabelParsing:
    def test_local_labels(self, tmp_path):
        sch = _parse_text(MINIMAL_SCH, tmp_path)
        assert len(sch.labels) == 2
        names = {l.text for l in sch.labels}
        assert names == {"VCC", "GND"}

    def test_global_label(self, tmp_path):
        sch = _parse_text(GLOBAL_LABEL_SCH, tmp_path)
        assert len(sch.global_labels) == 1
        gl = sch.global_labels[0]
        assert gl.text == "UART_TX"
        assert gl.x == pytest.approx(50.0)

    def test_no_connect(self, tmp_path):
        sch = _parse_text(GLOBAL_LABEL_SCH, tmp_path)
        assert len(sch.no_connects) == 1
        nc = sch.no_connects[0]
        assert nc.x == pytest.approx(20.0)
        assert nc.y == pytest.approx(30.0)


HIER_SCH = textwrap.dedent("""\
(kicad_sch
  (version 20231120)
  (generator kicad_condenser_test)
  (uuid "eeeeeeee-0000-0000-0000-000000000001")

  (hierarchical_label "DATA" (shape bidirectional) (at 30 40 0))

  (sheet (at 10 10 0) (size 20 10)
    (property "Sheetname" "SubSheet" (id 0) (at 0 0 0))
    (property "Sheetfile" "sub.kicad_sch" (id 1) (at 0 0 0))
    (uuid "ffffffff-0000-0000-0000-000000000001")
    (pin "DATA" bidirectional (at 10 10 0)
      (effects (font (size 1.27 1.27)))
      (uuid "11111111-0000-0000-0000-000000000001")
    )
  )
)
""")


class TestHierarchicalParsing:
    def test_hier_label(self, tmp_path):
        sch = _parse_text(HIER_SCH, tmp_path)
        assert len(sch.hier_labels) == 1
        hl = sch.hier_labels[0]
        assert hl.text == "DATA"
        assert hl.shape == "bidirectional"

    def test_sheet_parsed(self, tmp_path):
        sch = _parse_text(HIER_SCH, tmp_path)
        assert len(sch.sheets) == 1
        sheet = sch.sheets[0]
        assert sheet.sheet_name == "SubSheet"
        assert sheet.file_name == "sub.kicad_sch"

    def test_sheet_pin(self, tmp_path):
        sch = _parse_text(HIER_SCH, tmp_path)
        sheet = sch.sheets[0]
        assert len(sheet.pins) == 1
        pin = sheet.pins[0]
        assert pin.name == "DATA"
        assert pin.electrical_type == "bidirectional"
