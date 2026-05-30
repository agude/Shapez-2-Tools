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


def cmd_gen(args: argparse.Namespace) -> None:
    """Generate a blueprint from a parametric template."""
    from shapez2_tools import generator

    bp = generator.generate_rotator(args.direction, platform=args.platform)
    if args.output:
        bp.to_file(args.output)
        print(f"Wrote {args.output}")
    else:
        print(bp.to_string())


def cmd_diff(args: argparse.Namespace) -> None:
    """Compare two blueprints by functional entities."""
    from shapez2_tools import generator

    a = Blueprint.from_file(args.a)
    b = Blueprint.from_file(args.b)
    d = generator.diff_functional(a, b)
    only_a = sum(d["only_in_first"].values())
    only_b = sum(d["only_in_second"].values())
    if not only_a and not only_b:
        print("Functionally identical")
        return
    print(f"only in {args.a}: {only_a} entities")
    print(f"only in {args.b}: {only_b} entities")


def cmd_show(args: argparse.Namespace) -> None:
    """Render a blueprint layer as a text map."""
    from shapez2_tools import generator

    bp = Blueprint.from_file(args.file)
    print(generator.render_text(bp, layer=args.layer))


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

    # gen command
    gen = subparsers.add_parser("gen", help="Generate a blueprint")
    gen_sub = gen.add_subparsers(dest="kind", required=True)
    gen_rotate = gen_sub.add_parser("rotate", help="Rotator platform")
    gen_rotate.add_argument("direction", choices=["180", "cw", "ccw"])
    gen_rotate.add_argument("--platform", default="1x1", choices=["1x1", "1x4"])
    gen_rotate.add_argument("-o", "--output", type=Path, help="Output blueprint file")
    gen_rotate.set_defaults(func=cmd_gen)

    # diff command
    diff = subparsers.add_parser("diff", help="Compare two blueprints functionally")
    diff.add_argument("a", type=Path, help="First blueprint")
    diff.add_argument("b", type=Path, help="Second blueprint")
    diff.set_defaults(func=cmd_diff)

    # show command
    show = subparsers.add_parser("show", help="Render a blueprint layer as text")
    show.add_argument("file", type=Path, help="Blueprint file")
    show.add_argument("--layer", type=int, default=0, help="Floor 0/1/2")
    show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
