"""Command-line interface for shapez2-tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shapez2_tools.blueprint import Blueprint


def cmd_decode(args: argparse.Namespace) -> None:
    """Decode blueprint to JSON."""
    bp = Blueprint.from_file(args.file)
    output = bp.to_json()
    if args.output:
        args.output.write_text(output)
        print(f"Wrote {args.output}")
    else:
        print(output)


def cmd_encode(args: argparse.Namespace) -> None:
    """Encode JSON to blueprint."""
    data = json.loads(args.file.read_text())
    bp = Blueprint(data, args.version)
    output = bp.to_string()
    if args.output:
        args.output.write_text(output)
        print(f"Wrote {args.output}")
    else:
        print(output)


def cmd_info(args: argparse.Namespace) -> None:
    """Show blueprint info."""
    bp = Blueprint.from_file(args.file)
    for k, v in bp.summary().items():
        print(f"{k}: {v}")


def cmd_icon(args: argparse.Namespace) -> None:
    """Get or set blueprint icon."""
    bp = Blueprint.from_file(args.file)
    if args.set:
        new_icon = [None if s.lower() == "null" else s for s in args.set]
        bp.icon = new_icon
        bp.to_file(args.file)
        print(f"Updated icon: {new_icon}")
    else:
        print(f"Icon: {bp.icon}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="shapez2",
        description="Shapez 2 blueprint tools",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # decode command
    decode = subparsers.add_parser("decode", help="Decode blueprint to JSON")
    decode.add_argument("file", type=Path, help="Blueprint file")
    decode.add_argument("-o", "--output", type=Path, help="Output JSON file")
    decode.set_defaults(func=cmd_decode)

    # encode command
    encode = subparsers.add_parser("encode", help="Encode JSON to blueprint")
    encode.add_argument("file", type=Path, help="JSON file")
    encode.add_argument("-o", "--output", type=Path, help="Output blueprint file")
    encode.add_argument("-v", "--version", type=int, default=1, help="Format version")
    encode.set_defaults(func=cmd_encode)

    # info command
    info = subparsers.add_parser("info", help="Show blueprint info")
    info.add_argument("file", type=Path, help="Blueprint file")
    info.set_defaults(func=cmd_info)

    # icon command
    icon = subparsers.add_parser("icon", help="Get or set blueprint icon")
    icon.add_argument("file", type=Path, help="Blueprint file")
    icon.add_argument(
        "--set",
        nargs=4,
        metavar=("S1", "S2", "S3", "S4"),
        help="Set icon slots (use 'null' for empty)",
    )
    icon.set_defaults(func=cmd_icon)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
