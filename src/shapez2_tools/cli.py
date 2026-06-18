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


def cmd_lift(args: argparse.Namespace) -> None:
    """Lift a blueprint layer to a netlist and summarize it."""
    from collections import Counter

    from shapez2_tools import interpret, lift
    from shapez2_tools.shapes import Shape

    bp = Blueprint.from_file(args.file)
    nl = lift.trace_layer(bp, args.layer)
    print(f"layer {args.layer}: {dict(Counter(n.kind for n in nl.nodes.values()))}")
    print(f"unmatched legs: {lift.unmatched_legs(bp, args.layer)}")
    print(f"edges: {dict(lift.edge_kinds(nl))}")
    machines = Counter(
        n.type.replace("InternalVariant", "") for n in nl.nodes.values() if n.kind == "machine"
    )
    if machines:
        print(f"machines: {dict(machines)}")
    try:
        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        out = interpret.interpret(nl, inputs)
        print(f"interpret RuCuSuWu -> {dict(Counter(str(s) for s in out.values()))}")
    except Exception as exc:
        print(f"interpret: n/a ({exc})")


def cmd_viz(args: argparse.Namespace) -> None:
    """Render a blueprint layer as an interactive HTML/SVG page."""
    from shapez2_tools import viz

    bp = Blueprint.from_file(args.file)
    title = args.file.stem.replace("_", " ").title()
    html = viz.render_html(bp, layer=args.layer, title=title)

    out = args.output or args.file.with_suffix(".html")
    out.write_text(html)
    print(f"Wrote {out}")

    if args.open:
        import subprocess

        subprocess.Popen(
            ["xdg-open", str(out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def cmd_synth(args: argparse.Namespace) -> None:
    """Synthesize a blueprint from a spec."""
    from shapez2_tools import lift, viz

    if args.op == "swap_diagonal":
        from shapez2_tools.synth import DiagonalSpec, synthesize_diagonal

        spec = DiagonalSpec(pairs=args.pairs, platform=args.platform)
        print(f"spec: swap_diagonal on {spec.platform}, pairs={spec.pairs}")
        print(f"machines: {spec.pairs} swappers, ports: {spec.ports_needed}")

        result = synthesize_diagonal(spec)

        nl = lift.trace_layer(result, 0)
        n_edges = len(nl.edges)
        expected = spec.pairs * 4
        print(f"routed: {n_edges}/{expected} edges")

        if args.output:
            result.to_file(args.output)
            print(f"Wrote blueprint: {args.output}")

        title = f"synth swap_diagonal ({n_edges}/{expected} edges)"
        html = viz.render_html(result, layer=0, title=title)
        viz_out = args.viz_output or Path("synth_swap_diagonal.html")
        viz_out.write_text(html)
        print(f"Wrote viz: {viz_out}")
    else:
        from shapez2_tools.synth import Spec, synthesize

        ops = tuple(args.op.split(",")) if "," in args.op else args.op
        spec = Spec(op=ops, platform=args.platform, throughput=args.throughput)
        stages = spec.stages
        n_machines = spec.lanes * spec.throughput * len(stages)
        print(f"spec: {'+'.join(stages)} on {spec.platform}, throughput={spec.throughput}")
        print(f"lanes: {spec.lanes}, machines: {n_machines}")

        result = synthesize(spec)

        nl = lift.trace_layer(result, 0)
        n_edges = len(nl.edges)
        expected = spec.lanes * spec.throughput * (len(stages) + 1)
        print(f"routed: {n_edges}/{expected} edges")

        if args.output:
            result.to_file(args.output)
            print(f"Wrote blueprint: {args.output}")

        title = f"synth {'+'.join(stages)} ({n_edges}/{expected} edges)"
        html = viz.render_html(result, layer=0, title=title)
        viz_out = args.viz_output or Path(f"synth_{'_'.join(stages)}.html")
        viz_out.write_text(html)
        print(f"Wrote viz: {viz_out}")

    if not args.no_open:
        import subprocess

        subprocess.Popen(
            ["xdg-open", str(viz_out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def cmd_place(args: argparse.Namespace) -> None:
    """Re-place and re-route a blueprint via CP-SAT, then visualize."""
    from shapez2_tools import lift, viz
    from shapez2_tools.generator import Entity
    from shapez2_tools.place import abstract_netlist, place
    from shapez2_tools.route import entities_to_blueprint, reroute_with_junctions

    bp = Blueprint.from_file(args.file)
    original = lift.trace_layer(bp, args.layer)

    platform = args.platform or bp.entries[0].get("T", "Foundation_1x1")
    print(f"platform: {platform}")
    print(f"original: {len(original.nodes)} nodes, {len(original.edges)} edges")

    abstract = abstract_netlist(original)
    placed = place(abstract, platform)
    print(f"placed: {len(placed.nodes)} nodes")

    entities = [
        Entity(
            type=node.type,
            x=node.x,
            y=node.y,
            rotation=node.rotation,
            layer=args.layer,
        )
        for node in placed.nodes.values()
    ]
    stripped_bp = entities_to_blueprint(entities, platform=platform)
    routed_bp = reroute_with_junctions(stripped_bp, placed, layer=args.layer)

    routed_nl = lift.trace_layer(routed_bp, args.layer)
    original_edge_set = set(original.edges)
    routed_edge_set = set(routed_nl.edges)
    n_original = len(original_edge_set)
    n_routed = len(routed_edge_set)
    print(f"routed: {n_routed}/{n_original} edges")

    # Identify failed edges (in placed netlist but not realized after routing).
    # Map original abstract edges to placed coordinates for overlay.
    failed: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for src, dst in placed.edges:
        found = False
        for rs, rd in routed_nl.edges:
            if rs == src and rd == dst:
                found = True
                break
        if not found:
            failed.append((src, dst))

    if failed:
        print(f"failed edges: {len(failed)}")

    if args.output:
        routed_bp.to_file(args.output)
        print(f"Wrote blueprint: {args.output}")

    title = f"{args.file.stem} — placed ({n_routed}/{n_original} edges)"
    html = viz.render_html(routed_bp, layer=args.layer, failed_edges=failed, title=title)
    viz_out = args.viz_output or args.file.with_name(args.file.stem + "_placed.html")
    viz_out.write_text(html)
    print(f"Wrote viz: {viz_out}")

    if not args.no_open:
        import subprocess

        subprocess.Popen(
            ["xdg-open", str(viz_out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )


def cmd_route(args: argparse.Namespace) -> None:
    """Route missing connections into a half-completed blueprint, in place."""
    from collections import Counter

    from shapez2_tools import lift, pathfinder, route_only, viz

    bp = Blueprint.from_file(args.file)
    layers = [args.layer] if args.layer is not None else [0, 1, 2]
    hop_range = args.hop_range or lift.MAX_HOP_RANGE
    platform = args.platform or bp.entries[0].get("T", "Foundation_1x1")

    clone_targets = getattr(args, "clone", None) or []
    for layer in layers:
        dangles = route_only.find_and_classify_dangles(bp, layer)
        if not dangles:
            print(f"layer {layer}: no dangling ends, skipping")
            continue
        counts = Counter(d.half for d in dangles)
        print(
            f"layer {layer}: {len(dangles)} dangles ({counts['west']} west, {counts['east']} east)"
        )

        ports = route_only.find_free_port_positions(bp, layer)
        west_ports, east_ports = route_only.partition_ports(ports, platform)
        west_dangles = [(d.x, d.y) for d in dangles if d.half == "west"]
        east_dangles = [(d.x, d.y) for d in dangles if d.half == "east"]
        n_matched = len(route_only.match_dangles_to_ports(west_dangles, west_ports)) + len(
            route_only.match_dangles_to_ports(east_dangles, east_ports)
        )
        print(f"layer {layer}: {n_matched}/{len(dangles)} dangles matched to ports")

        clone_for_layer = [t for t in clone_targets if t != layer]
        try:
            bp = route_only.route_and_merge(
                bp,
                layer,
                hop_range=hop_range,
                platform=platform,
                clone_to_layers=clone_for_layer,
            )
        except pathfinder.RoutingError as exc:
            print(f"layer {layer}: routing failed ({exc}), leaving layer unchanged")
            continue

        cloned = f", cloned to {clone_for_layer}" if clone_for_layer else ""
        remaining = lift.unmatched_legs(bp, layer)
        print(f"layer {layer}: routed, {remaining} unmatched legs remaining{cloned}")

    bp.to_file(args.output)
    print(f"Wrote {args.output}")

    if args.viz:
        title = args.file.stem.replace("_", " ").title()
        for layer in layers:
            html = viz.render_html(bp, layer=layer, title=f"{title} (layer {layer})")
            viz_out = args.output.with_name(f"{args.output.stem}_layer{layer}.html")
            viz_out.write_text(html)
            print(f"Wrote viz: {viz_out}")


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
    encode.add_argument("-v", "--version", type=int, default=4, help="Format version")
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

    # lift command
    lift_cmd = subparsers.add_parser("lift", help="Lift a blueprint to a netlist")
    lift_cmd.add_argument("file", type=Path, help="Blueprint file")
    lift_cmd.add_argument("--layer", type=int, default=0, help="Floor 0/1/2")
    lift_cmd.set_defaults(func=cmd_lift)

    # viz command
    viz_cmd = subparsers.add_parser("viz", help="Render a blueprint as HTML/SVG")
    viz_cmd.add_argument("file", type=Path, help="Blueprint file")
    viz_cmd.add_argument("-o", "--output", type=Path, help="Output HTML file")
    viz_cmd.add_argument("--layer", type=int, default=0, help="Floor 0/1/2")
    viz_cmd.add_argument("--open", action="store_true", help="Open in browser")
    viz_cmd.set_defaults(func=cmd_viz)

    # synth command
    synth_cmd = subparsers.add_parser("synth", help="Synthesize a blueprint from a spec")
    synth_cmd.add_argument(
        "op",
        help="Operation(s): comma-separated for series chain, or 'swap_diagonal'",
    )
    synth_cmd.add_argument("--platform", default="Foundation_1x1")
    synth_cmd.add_argument("--throughput", type=int, default=2)
    synth_cmd.add_argument("--pairs", type=int, default=2, help="Swapper pairs (swap_diagonal)")
    synth_cmd.add_argument("-o", "--output", type=Path, help="Output blueprint file")
    synth_cmd.add_argument("--viz-output", type=Path, help="Output HTML viz file")
    synth_cmd.add_argument("--no-open", action="store_true", help="Don't open in browser")
    synth_cmd.set_defaults(func=cmd_synth)

    # place command
    place_cmd = subparsers.add_parser("place", help="Re-place and re-route a blueprint via CP-SAT")
    place_cmd.add_argument("file", type=Path, help="Source blueprint file")
    place_cmd.add_argument("-o", "--output", type=Path, help="Output blueprint file")
    place_cmd.add_argument("--viz-output", type=Path, help="Output HTML viz file")
    place_cmd.add_argument("--platform", type=str, help="Platform type (auto-detected)")
    place_cmd.add_argument("--layer", type=int, default=0, help="Floor 0/1/2")
    place_cmd.add_argument("--no-open", action="store_true", help="Don't open in browser")
    place_cmd.set_defaults(func=cmd_place)

    # route command
    route_cmd = subparsers.add_parser(
        "route", help="Route missing connections into a half-completed blueprint"
    )
    route_cmd.add_argument("file", type=Path, help="Half-completed blueprint file")
    route_cmd.add_argument("-o", "--output", type=Path, required=True, help="Output blueprint file")
    route_cmd.add_argument("--platform", type=str, help="Platform type (auto-detected)")
    route_cmd.add_argument("--layer", type=int, help="Floor 0/1/2 (default: all)")
    route_cmd.add_argument("--hop-range", type=int, help="Override hop range")
    route_cmd.add_argument("--viz", action="store_true", help="Generate HTML visualization")
    route_cmd.add_argument(
        "--clone",
        type=int,
        nargs="+",
        metavar="LAYER",
        help="Clone the routing solution to these layers (e.g. --clone 1 2)",
    )
    route_cmd.set_defaults(func=cmd_route)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
