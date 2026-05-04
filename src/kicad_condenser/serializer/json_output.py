"""JSON serializer for the condensed netlist.

Converts a :class:`~kicad_condenser.models.netlist.Netlist` into a plain
Python dict ready for ``json.dumps``.  No positional information is included.

Public API
----------
serialize(netlist: Netlist) -> dict
to_json(netlist: Netlist, *, indent: int | None = None) -> str
"""

from __future__ import annotations

import json

from kicad_condenser.models.netlist import Netlist


def serialize(netlist: Netlist) -> dict:
    """Convert *netlist* to a JSON-serializable dictionary.

    Schema
    ------
    ::

        {
          "project": "my_project",
          "components": [
            {
              "reference": "R1",
              "value": "10k",
              "footprint": "Resistor_SMD:R_0402",
              "datasheet": "~",
              "properties": { "ki_description": "Resistor" },
              "pins": [
                { "number": "1", "name": "~", "type": "passive", "net": "VCC" },
                { "number": "2", "name": "~", "type": "passive", "net": "GND" }
              ]
            }
          ],
          "nets": [
            {
              "name": "VCC",
              "pins": [
                { "reference": "R1", "pin": "1" }
              ]
            }
          ]
        }
    """
    return {
        "project": netlist.project,
        "components": [
            {
                "reference": comp.reference,
                "value": comp.value,
                "footprint": comp.footprint,
                "datasheet": comp.datasheet,
                "properties": comp.properties,
                "pins": [
                    {
                        "number": pin.number,
                        "name": pin.name,
                        "type": pin.electrical_type,
                        "net": pin.net,
                    }
                    for pin in comp.pins
                ],
            }
            for comp in netlist.components
        ],
        "nets": [
            {
                "name": net.name,
                "pins": [
                    {"reference": pr.reference, "pin": pr.pin}
                    for pr in net.pins
                ],
            }
            for net in netlist.nets
        ],
    }


def to_json(netlist: Netlist, *, indent: int | None = None) -> str:
    """Serialize *netlist* to a JSON string.

    Parameters
    ----------
    netlist:
        The resolved netlist to serialize.
    indent:
        If provided, pretty-print with this many spaces per indentation level.
    """
    return json.dumps(serialize(netlist), indent=indent, ensure_ascii=False)
