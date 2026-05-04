"""Unit tests for the net resolver."""

import textwrap

import pytest

from kicad_condenser.netlist.resolver import resolve
from kicad_condenser.models.netlist import Netlist


# ---------------------------------------------------------------------------
# Full single-sheet voltage-divider schematic
# ---------------------------------------------------------------------------
# Topology:
#   VCC --[R1 pin1]--[R1 pin2]--MID--[R2 pin1]--[R2 pin2]-- GND
#
# Wire layout (all vertical, x=10):
#   y=5  : VCC label
#   y=5..9.994 : wire
#   y=9.994 : R1 pin 1 (sym at 10,10, angle=0, pin at y=+1.016 → y=10-1.016=8.984 ... wait)
#
# KiCad's Y-axis increases downward.  For a resistor at (10,10) angle=0:
#   pin 1 is at local (0, +1.016) → absolute (10, 10+1.016) = (10, 11.016)  -- BOTTOM
#   pin 2 is at local (0, -1.016) → absolute (10, 10-1.016) = (10,  8.984)  -- TOP
#
# Wait: the pin definitions in the library are:
#   pin1: (at 0 1.016 270)   i.e. local y=+1.016 → absolute y = sym_y + 1.016
#   pin2: (at 0 -1.016 90)   i.e. local y=-1.016 → absolute y = sym_y - 1.016
#
# So for R1 at (10, 10, angle=0):
#   pin1 absolute = (10, 11.016)  → connects to wire going DOWN to GND
#   pin2 absolute = (10, 8.984)   → connects to wire going UP to VCC
#
# For R2 at (10, 20, angle=0):
#   pin1 absolute = (10, 21.016)  → GND label
#   pin2 absolute = (10, 18.984)  → MID net
#
# Wires:
#   VCC:  (10, 5) - (10, 8.984)     → connects to R1-pin2
#   MID:  (10, 11.016) - (10, 18.984) → connects R1-pin1 to R2-pin2
#   GND:  (10, 21.016) - (10, 25)   → connects to R2-pin1

VOLTAGE_DIVIDER_SCH = textwrap.dedent("""\
(kicad_sch
  (version 20231120)
  (generator kicad_condenser_test)
  (uuid "aaaaaaaa-1111-0000-0000-000000000001")

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
    (uuid "r1-uuid-0000-0000-0000-000000000001")
    (property "Reference" "R1" (id 0) (at 10 10 0))
    (property "Value" "10k" (id 1) (at 10 10 0))
    (property "Footprint" "Resistor_SMD:R_0402" (id 2) (at 10 10 0))
    (property "Datasheet" "~" (id 3) (at 10 10 0))
    (instances
      (project "test"
        (path "/aaaaaaaa-1111-0000-0000-000000000001"
          (reference "R1")
          (unit 1)
        )
      )
    )
  )

  (symbol "Device:R" (at 10 20 0) (unit 1) (in_bom yes) (on_board yes)
    (uuid "r2-uuid-0000-0000-0000-000000000001")
    (property "Reference" "R2" (id 0) (at 10 20 0))
    (property "Value" "22k" (id 1) (at 10 20 0))
    (property "Footprint" "Resistor_SMD:R_0402" (id 2) (at 10 20 0))
    (property "Datasheet" "~" (id 3) (at 10 20 0))
    (instances
      (project "test"
        (path "/aaaaaaaa-1111-0000-0000-000000000001"
          (reference "R2")
          (unit 1)
        )
      )
    )
  )

  (wire (pts (xy 10 5) (xy 10 8.984)))
  (wire (pts (xy 10 11.016) (xy 10 18.984)))
  (wire (pts (xy 10 21.016) (xy 10 25)))

  (label "VCC" (at 10 5 0))
  (label "MID" (at 10 11.016 0))
  (label "GND" (at 10 25 0))
)
""")


def _run(text: str, tmp_path) -> Netlist:
    path = tmp_path / "test.kicad_sch"
    path.write_text(text, encoding="utf-8")
    return resolve(path)


class TestVoltageDivider:
    def test_two_components(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        refs = {c.reference for c in nl.components}
        assert refs == {"R1", "R2"}

    def test_component_values(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        assert by_ref["R1"].value == "10k"
        assert by_ref["R2"].value == "22k"

    def test_r1_pin2_net_is_vcc(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r1_pins = {p.number: p for p in by_ref["R1"].pins}
        assert r1_pins["2"].net == "VCC"

    def test_r1_pin1_net_is_mid(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r1_pins = {p.number: p for p in by_ref["R1"].pins}
        assert r1_pins["1"].net == "MID"

    def test_r2_pin2_net_is_mid(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r2_pins = {p.number: p for p in by_ref["R2"].pins}
        assert r2_pins["2"].net == "MID"

    def test_r2_pin1_net_is_gnd(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r2_pins = {p.number: p for p in by_ref["R2"].pins}
        assert r2_pins["1"].net == "GND"

    def test_three_nets(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        names = {n.name for n in nl.nets}
        assert names == {"VCC", "MID", "GND"}

    def test_net_pins_correct(self, tmp_path):
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        by_name = {n.name: n for n in nl.nets}
        vcc_pins = {(p.reference, p.pin) for p in by_name["VCC"].pins}
        assert ("R1", "2") in vcc_pins
        gnd_pins = {(p.reference, p.pin) for p in by_name["GND"].pins}
        assert ("R2", "1") in gnd_pins

    def test_no_positional_info_in_output(self, tmp_path):
        from kicad_condenser.serializer.json_output import serialize
        nl = _run(VOLTAGE_DIVIDER_SCH, tmp_path)
        output = serialize(nl)
        # Recursively scan the dict for any key that sounds positional
        positional_keys = {"x", "y", "at", "angle", "xy", "position"}
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k not in positional_keys, f"Positional key '{k}' found in output"
                    scan(v)
            elif isinstance(obj, list):
                for item in obj:
                    scan(item)
        scan(output)


class TestNoConnect:
    NO_CONNECT_SCH = textwrap.dedent("""\
(kicad_sch
  (version 20231120)
  (generator kicad_condenser_test)
  (uuid "aaaaaaaa-2222-0000-0000-000000000001")

  (lib_symbols
    (symbol "Device:R"
      (in_bom yes)
      (on_board yes)
      (property "Reference" "R" (id 0) (at 0 0 0))
      (property "Value" "R" (id 1) (at 0 0 0))
      (property "Footprint" "" (id 2) (at 0 0 0))
      (property "Datasheet" "~" (id 3) (at 0 0 0))
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
    (uuid "r1-nc-uuid-0000-0000-000000000001")
    (property "Reference" "R1" (id 0) (at 10 10 0))
    (property "Value" "1k" (id 1) (at 10 10 0))
    (property "Footprint" "" (id 2) (at 10 10 0))
    (property "Datasheet" "~" (id 3) (at 10 10 0))
    (instances
      (project "test"
        (path "/aaaaaaaa-2222-0000-0000-000000000001"
          (reference "R1")
          (unit 1)
        )
      )
    )
  )

  (wire (pts (xy 10 8.984) (xy 10 5)))
  (label "VCC" (at 10 5 0))
  (no_connect (at 10 11.016 0) (uuid "nc-uuid-0000-0000-0000-000000000001"))
)
""")

    def test_no_connect_pin_marked_nc(self, tmp_path):
        nl = _run(self.NO_CONNECT_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r1_pins = {p.number: p for p in by_ref["R1"].pins}
        assert r1_pins["1"].net == "__NC__"

    def test_connected_pin_has_net(self, tmp_path):
        nl = _run(self.NO_CONNECT_SCH, tmp_path)
        by_ref = {c.reference: c for c in nl.components}
        r1_pins = {p.number: p for p in by_ref["R1"].pins}
        assert r1_pins["2"].net == "VCC"
