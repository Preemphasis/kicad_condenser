"""Command-line interface for kicad-condenser.

Usage
-----
kicad-condenser <PATH> [--output FILE] [--pretty]

  PATH     Path to a .kicad_sch file or a directory containing one.
           If a directory is given, the first .kicad_sch file found at
           the top level is used as the root schematic.

  --output FILE   Write JSON to FILE instead of stdout.
  --pretty        Pretty-print JSON with 2-space indentation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kicad_condenser.netlist.resolver import resolve
from kicad_condenser.serializer.json_output import serialize


def _find_root_schematic(path: Path) -> Path:
    """Return the root .kicad_sch path for *path*.

    If *path* is a directory, look for a .kicad_sch file there.
    Prefers a file whose stem matches the directory name (the KiCad convention
    for the root schematic), then falls back to the first .kicad_sch found.
    """
    if path.is_file():
        return path

    if path.is_dir():
        # Prefer <dir>/<dir_name>.kicad_sch
        preferred = path / f"{path.name}.kicad_sch"
        if preferred.exists():
            return preferred
        # Fallback: first .kicad_sch at the top level
        candidates = sorted(path.glob("*.kicad_sch"))
        if candidates:
            return candidates[0]

    raise FileNotFoundError(
        f"No .kicad_sch file found at: {path}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kicad-condenser",
        description="Condense a KiCad schematic into a positional-free JSON netlist.",
    )
    parser.add_argument(
        "path",
        metavar="PATH",
        help="Path to a .kicad_sch file or a directory containing one.",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        default=None,
        help="Write JSON output to FILE (default: stdout).",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON with 2-space indentation.",
    )

    args = parser.parse_args(argv)

    try:
        root_path = _find_root_schematic(Path(args.path))
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        netlist = resolve(root_path)
    except Exception as exc:  # noqa: BLE001
        print(f"Error parsing schematic: {exc}", file=sys.stderr)
        return 1

    indent = 2 if args.pretty else None
    output_dict = serialize(netlist)
    output_text = json.dumps(output_dict, indent=indent, ensure_ascii=False)

    if args.output:
        try:
            Path(args.output).write_text(output_text, encoding="utf-8")
        except OSError as exc:
            print(f"Error writing output: {exc}", file=sys.stderr)
            return 1
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
