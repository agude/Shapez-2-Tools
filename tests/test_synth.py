"""WP-E + WP-L: synthesis and lane assignment tests."""

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import functional_entities
from shapez2_tools.shapes import Shape
from shapez2_tools.synth import (
    SINK_TYPE,
    SRC_TYPE,
    DiagonalSpec,
    Spec,
    _monotone_sort,
    netlist_from_diagonal_spec,
    netlist_from_spec,
    synthesize,
    synthesize_diagonal,
    synthesize_quotient,
)
from tests.conftest import REF


class TestNetlistFromSpec:
    """Unit tests for the spec → abstract netlist builder."""

    def test_rotate_180_quarter_topology(self):
        """Rotate-180 on 1x1: 4 sources, 8 machines, 4 sinks, 16 edges."""
        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        abstract = netlist_from_spec(spec)

        by_kind = {}
        for n in abstract["nodes"]:
            by_kind.setdefault(n["kind"], []).append(n)

        assert len(by_kind["platform_in"]) == 4
        assert len(by_kind["platform_out"]) == 4
        assert len(by_kind["machine"]) == 8
        assert len(abstract["edges"]) == 16

    def test_machine_type_matches_op(self):
        spec = Spec(op="rotate_cw", platform="Foundation_1x1")
        abstract = netlist_from_spec(spec)
        machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]
        assert all(n["type"] == "RotatorOneQuadInternalVariant" for n in machines)

    def test_edge_structure_fan_out_fan_in(self):
        """Each source fans out to `throughput` machines; those fan in to one sink."""
        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        abstract = netlist_from_spec(spec)

        out_edges: dict[str, list[str]] = {}
        in_edges: dict[str, list[str]] = {}
        for s, d in abstract["edges"]:
            out_edges.setdefault(s, []).append(d)
            in_edges.setdefault(d, []).append(s)

        for n in abstract["nodes"]:
            if n["kind"] == "platform_in":
                assert len(out_edges[n["id"]]) == 2
            elif n["kind"] == "platform_out":
                assert len(in_edges[n["id"]]) == 2
            elif n["kind"] == "machine":
                assert len(out_edges[n["id"]]) == 1
                assert len(in_edges[n["id"]]) == 1

    def test_series_chain_topology(self):
        """Series chain: 4 lanes × 1 path × 2 stages = 8 machines, 12 edges."""
        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=1,
        )
        abstract = netlist_from_spec(spec)

        by_kind: dict[str, list] = {}
        for n in abstract["nodes"]:
            by_kind.setdefault(n["kind"], []).append(n)

        assert len(by_kind["platform_in"]) == 4
        assert len(by_kind["platform_out"]) == 4
        assert len(by_kind["machine"]) == 8
        # 4 lanes × (src→s0 + s0→s1 + s1→sink) = 12 edges
        assert len(abstract["edges"]) == 12

    def test_series_chain_edge_structure(self):
        """Series chain: each machine has exactly 1 in and 1 out edge."""
        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=1,
        )
        abstract = netlist_from_spec(spec)

        out_edges: dict[str, list[str]] = {}
        in_edges: dict[str, list[str]] = {}
        for s, d in abstract["edges"]:
            out_edges.setdefault(s, []).append(d)
            in_edges.setdefault(d, []).append(s)

        for n in abstract["nodes"]:
            if n["kind"] == "platform_in":
                assert len(out_edges[n["id"]]) == 1
            elif n["kind"] == "platform_out":
                assert len(in_edges[n["id"]]) == 1
            elif n["kind"] == "machine":
                assert len(out_edges[n["id"]]) == 1
                assert len(in_edges[n["id"]]) == 1

    def test_series_with_throughput_topology(self):
        """Series chain with throughput=2: fan-out at src, fan-in at sink."""
        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=2,
        )
        abstract = netlist_from_spec(spec)

        by_kind: dict[str, list] = {}
        for n in abstract["nodes"]:
            by_kind.setdefault(n["kind"], []).append(n)

        assert len(by_kind["platform_in"]) == 4
        assert len(by_kind["platform_out"]) == 4
        # 4 lanes × 2 paths × 2 stages = 16 machines
        assert len(by_kind["machine"]) == 16
        # 4 lanes × 2 paths × (src→s0 + s0→s1 + s1→sink) = 24 edges
        assert len(abstract["edges"]) == 24


class TestSynthesize:
    """End-to-end: synthesize → lift → compare with oracle."""

    def test_synth_rotate_180_quarter(self):
        """Synthesized rotate-180 quarter is isomorphic to the oracle."""
        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)

        oracle = Blueprint.from_file(REF / "quarter_rotate_180.spz2bp")
        oracle_nl = lift.trace_layer(oracle, 0)
        result_nl = lift.trace_layer(result, 0)

        assert lift.isomorphic(oracle_nl, result_nl)

    def test_synth_rotate_180_quarter_validate(self):
        """Synthesized blueprint passes physical validation."""
        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)
        assert lift.validate(result) == []

    def test_synth_rotate_180_quarter_interpret(self):
        """Synthesized blueprint computes rotate-180 on every lane."""
        from shapez2_tools import interpret

        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)
        nl = lift.trace_layer(result, 0)

        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("SuWuRuCu")
        assert all(s == expected for s in outputs.values())

    def test_synth_rotate_cw_quarter(self):
        """Synthesized rotate-CW quarter is isomorphic to the oracle."""
        spec = Spec(op="rotate_cw", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)

        oracle = Blueprint.from_file(REF / "quarter_rotate_cw.spz2bp")
        oracle_nl = lift.trace_layer(oracle, 0)
        result_nl = lift.trace_layer(result, 0)

        assert lift.isomorphic(oracle_nl, result_nl)

    def test_synth_rotate_ccw_quarter(self):
        """Synthesized rotate-CCW quarter is isomorphic to the oracle."""
        spec = Spec(op="rotate_ccw", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)

        oracle = Blueprint.from_file(REF / "quarter_rotate_ccw.spz2bp")
        oracle_nl = lift.trace_layer(oracle, 0)
        result_nl = lift.trace_layer(result, 0)

        assert lift.isomorphic(oracle_nl, result_nl)

    def test_synth_half_destroy_quarter(self):
        """Synthesized half-destroy quarter validates and interprets correctly."""
        from shapez2_tools import interpret

        spec = Spec(op="half_destroy", platform="Foundation_1x1", throughput=2)
        result = synthesize(spec)

        assert lift.validate(result) == []

        nl = lift.trace_layer(result, 0)
        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("RuCu----")
        assert all(s == expected for s in outputs.values())


class TestSeriesChain:
    """Series chain: multiple operations per lane."""

    def test_series_cw_cw_equals_180(self):
        """Two CW rotations in series = rotate-180, isomorphic to oracle."""
        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=1,
        )
        result = synthesize(spec)

        assert lift.validate(result) == []

        from shapez2_tools import interpret

        nl = lift.trace_layer(result, 0)
        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("SuWuRuCu")
        assert all(s == expected for s in outputs.values())

    def test_series_ccw_ccw_ccw_equals_cw(self):
        """Three CCW rotations = one CW rotation."""
        from shapez2_tools import interpret

        spec = Spec(
            op=("rotate_ccw", "rotate_ccw", "rotate_ccw"),
            platform="Foundation_1x1",
            throughput=1,
        )
        result = synthesize(spec)
        assert lift.validate(result) == []

        nl = lift.trace_layer(result, 0)
        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("WuRuCuSu")
        assert all(s == expected for s in outputs.values())

    def test_series_with_throughput(self):
        """Series chain with throughput=2: fan-out at src, fan-in at sink."""
        from shapez2_tools import interpret

        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=2,
        )
        result = synthesize(spec)
        assert lift.validate(result) == []

        nl = lift.trace_layer(result, 0)
        inputs = {
            p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("SuWuRuCu")
        assert all(s == expected for s in outputs.values())


class TestMultiCellPlacement:
    """Multi-cell machines (swappers, cutters) in the placer."""

    def _swapper_abstract(self) -> dict:
        """Build an abstract netlist for 2 swappers on Foundation_1x1.

        Topology: 4 sources, 2 swappers (each 2-in/2-out), 4 sinks.
        Pair 0: src0,src1 → swap0 → sink0,sink1
        Pair 1: src2,src3 → swap1 → sink2,sink3
        """
        nodes = [
            {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
            {"id": "src1", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
            {"id": "src2", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
            {"id": "src3", "type": "BeltPortReceiverInternalVariant", "kind": "platform_in"},
            {"id": "swap0", "type": "SwapperDefaultInternalVariant", "kind": "machine"},
            {"id": "swap1", "type": "SwapperDefaultInternalVariant", "kind": "machine"},
            {"id": "sink0", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
            {"id": "sink1", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
            {"id": "sink2", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
            {"id": "sink3", "type": "BeltPortSenderInternalVariant", "kind": "platform_out"},
        ]
        edges = [
            ("src0", "swap0"),
            ("src1", "swap0"),
            ("swap0", "sink0"),
            ("swap0", "sink1"),
            ("src2", "swap1"),
            ("src3", "swap1"),
            ("swap1", "sink2"),
            ("swap1", "sink3"),
        ]
        return {"nodes": nodes, "edges": edges}

    def test_swapper_placement_solves(self):
        """CP-SAT can place 2 swappers without overlap."""
        from shapez2_tools.place import place

        abstract = self._swapper_abstract()
        nl = place(abstract, "Foundation_1x1")

        machines = {p: n for p, n in nl.nodes.items() if n.kind == "machine"}
        assert len(machines) == 2
        assert all("Swapper" in n.type for n in machines.values())

    def test_swapper_second_cells_no_overlap(self):
        """Second cells don't overlap anchors or each other."""
        from shapez2_tools.place import place

        abstract = self._swapper_abstract()
        nl = place(abstract, "Foundation_1x1")

        all_cells: list[tuple[int, int]] = []
        for pos, node in nl.nodes.items():
            fp = lift._machine_footprint(node.type, node.rotation)
            for dx, dy, dl in fp:
                if dl == 0:
                    all_cells.append((pos[0] + dx, pos[1] + dy))
        assert len(all_cells) == len(set(all_cells)), f"overlap: {all_cells}"

    def test_swapper_lowered_validates(self):
        """Lowered swapper blueprint passes physical validation."""
        from shapez2_tools.synth import _lower

        abstract = self._swapper_abstract()
        bp = _lower(abstract, "Foundation_1x1")
        errors = lift.validate(bp)
        assert errors == []

    def test_swapper_lowered_interprets(self):
        """Lowered swapper produces diagonal shapes."""
        from shapez2_tools import interpret
        from shapez2_tools.synth import _lower

        abstract = self._swapper_abstract()
        bp = _lower(abstract, "Foundation_1x1")
        nl = lift.trace_layer(bp, 0)

        srcs = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "platform_in"],
            key=lambda pn: pn[0][0],
        )
        sinks = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "platform_out"],
            key=lambda pn: pn[0][0],
        )

        north = Shape.parse("Ru----Ru")  # NE + NW
        south = Shape.parse("--RuRu--")  # SE + SW
        inputs = {}
        for i, (pos, _) in enumerate(srcs):
            inputs[pos] = north if i % 2 == 0 else south

        outputs = interpret.interpret(nl, inputs)
        out_shapes = {str(outputs[p]) for p, _ in sinks}
        assert "Ru--Ru--" in out_shapes or "--Ru--Ru" in out_shapes


class TestDiagonalNetlist:
    """Unit tests for the diagonal-trick abstract netlist builder."""

    def test_two_pair_topology(self):
        """2 pairs: 4 sources, 2 swappers, 4 sinks, 8 edges."""
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        abstract = netlist_from_diagonal_spec(spec)

        by_kind: dict[str, list] = {}
        for n in abstract["nodes"]:
            by_kind.setdefault(n["kind"], []).append(n)

        assert len(by_kind["platform_in"]) == 4
        assert len(by_kind["platform_out"]) == 4
        assert len(by_kind["machine"]) == 2
        assert len(abstract["edges"]) == 8

    def test_machine_type_is_swapper(self):
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        abstract = netlist_from_diagonal_spec(spec)
        machines = [n for n in abstract["nodes"] if n["kind"] == "machine"]
        assert all("Swapper" in n["type"] for n in machines)

    def test_each_swapper_has_two_in_two_out(self):
        """Each swapper has exactly 2 inputs and 2 outputs."""
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        abstract = netlist_from_diagonal_spec(spec)

        in_edges: dict[str, list[str]] = {}
        out_edges: dict[str, list[str]] = {}
        for s, d in abstract["edges"]:
            out_edges.setdefault(s, []).append(d)
            in_edges.setdefault(d, []).append(s)

        for n in abstract["nodes"]:
            if n["kind"] == "machine":
                assert len(in_edges[n["id"]]) == 2
                assert len(out_edges[n["id"]]) == 2

    def test_sources_interleaved_north_south(self):
        """Source IDs alternate north/south per pair."""
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        abstract = netlist_from_diagonal_spec(spec)
        src_ids = [n["id"] for n in abstract["nodes"] if n["kind"] == "platform_in"]
        assert src_ids == ["src0_n", "src0_s", "src1_n", "src1_s"]

    def test_too_many_pairs_raises(self):
        """Requesting more pairs than ports allows raises ValueError."""
        spec = DiagonalSpec(pairs=3, platform="Foundation_1x1")
        with pytest.raises(ValueError, match="6 ports"):
            netlist_from_diagonal_spec(spec)

    def test_four_pair_topology(self):
        """4 pairs on 2x2: 8 sources, 4 swappers, 8 sinks, 16 edges."""
        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        abstract = netlist_from_diagonal_spec(spec)

        by_kind: dict[str, list] = {}
        for n in abstract["nodes"]:
            by_kind.setdefault(n["kind"], []).append(n)

        assert len(by_kind["platform_in"]) == 8
        assert len(by_kind["platform_out"]) == 8
        assert len(by_kind["machine"]) == 4
        assert len(abstract["edges"]) == 16

    def test_four_pair_too_many_raises(self):
        """5 pairs need 10 ports; Foundation_2x2 has only 8."""
        spec = DiagonalSpec(pairs=5, platform="Foundation_2x2")
        with pytest.raises(ValueError, match="10 ports"):
            netlist_from_diagonal_spec(spec)


class TestDiagonalSynthesize:
    """End-to-end: synthesize diagonal trick → validate → interpret."""

    def test_diagonal_validates(self):
        """Synthesized diagonal-trick blueprint passes physical validation."""
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        result = synthesize_diagonal(spec)
        errors = lift.validate(result)
        assert errors == []

    def test_diagonal_edge_count(self):
        """All 8 edges are realized (4 src→swap + 4 swap→sink)."""
        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        result = synthesize_diagonal(spec)
        nl = lift.trace_layer(result, 0)
        assert len(nl.edges) == 8

    def test_diagonal_interprets(self):
        """Feeding north/south halves produces the two diagonals."""
        from shapez2_tools import interpret

        spec = DiagonalSpec(pairs=2, platform="Foundation_1x1")
        result = synthesize_diagonal(spec)
        nl = lift.trace_layer(result, 0)

        srcs = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "platform_in"],
            key=lambda pn: pn[0][0],
        )

        north = Shape.parse("Ru----Ru")  # NE + NW
        south = Shape.parse("--RuRu--")  # SE + SW
        inputs = {}
        for i, (pos, _) in enumerate(srcs):
            inputs[pos] = north if i % 2 == 0 else south

        outputs = interpret.interpret(nl, inputs)
        out_shapes = {str(s) for s in outputs.values()}
        assert "Ru--Ru--" in out_shapes  # upper-left diagonal
        assert "--Ru--Ru" in out_shapes  # upper-right diagonal


class TestDiagonalSynthesize4Pair:
    """4-pair diagonal trick on Foundation_2x2 — the full-belt target."""

    def test_validates(self):
        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        result = synthesize_diagonal(spec)
        assert lift.validate(result) == []

    def test_edge_count(self):
        """All 16 edges realized (8 src→swap + 8 swap→sink)."""
        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        result = synthesize_diagonal(spec)
        nl = lift.trace_layer(result, 0)
        assert len(nl.edges) == 16

    def test_unmatched_legs(self):
        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        result = synthesize_diagonal(spec)
        assert lift.unmatched_legs(result, 0) == 0

    def test_interprets(self):
        """Feeding north/south halves produces the two diagonals on all 8 lanes."""
        from shapez2_tools import interpret

        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        result = synthesize_diagonal(spec)
        nl = lift.trace_layer(result, 0)

        srcs = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "platform_in"],
            key=lambda pn: pn[0][0],
        )
        assert len(srcs) == 8

        north = Shape.parse("Ru----Ru")
        south = Shape.parse("--RuRu--")
        inputs = {}
        for i, (pos, _) in enumerate(srcs):
            inputs[pos] = north if i % 2 == 0 else south

        outputs = interpret.interpret(nl, inputs)
        assert len(outputs) == 8

        out_shapes = {str(s) for s in outputs.values()}
        assert "Ru--Ru--" in out_shapes
        assert "--Ru--Ru" in out_shapes


# ---------------------------------------------------------------------------
# WP-L: monotone lane assignment + symmetry quotient
# ---------------------------------------------------------------------------


def _count_inversions(nl: lift.Netlist) -> int:
    """Count source→sink x-order inversions in a placed netlist.

    For each source (sorted by x), trace through edges to find reachable
    sinks.  An inversion is a pair (i, j) where source i is left of source j
    but source i's mean sink x is right of source j's.
    """
    srcs = sorted(
        [p for p, n in nl.nodes.items() if n.kind == "platform_in"],
        key=lambda p: p[0],
    )
    edge_out: dict[tuple, list[tuple]] = {}
    for s, d in nl.edges:
        edge_out.setdefault(s, []).append(d)

    def _reachable_sinks(start):
        visited: set[tuple] = set()
        queue = [start]
        sinks: list[tuple] = []
        while queue:
            pos = queue.pop(0)
            if pos in visited:
                continue
            visited.add(pos)
            node = nl.nodes.get(pos)
            if node and node.kind == "platform_out":
                sinks.append(pos)
                continue
            queue.extend(edge_out.get(pos, []))
        return sinks

    sink_xs: list[float] = []
    for src_pos in srcs:
        sinks = _reachable_sinks(src_pos)
        sink_xs.append(sum(p[0] for p in sinks) / len(sinks) if sinks else 0.0)

    return sum(
        1
        for i in range(len(sink_xs))
        for j in range(i + 1, len(sink_xs))
        if sink_xs[i] > sink_xs[j]
    )


class TestMonotoneAssignment:
    """WP-L: monotone lane assignment minimizes route crossings."""

    def test_monotone_assignment_no_inversions(self):
        """Uniform spec ⇒ zero inversions between source and sink x-orders."""
        from shapez2_tools.place import place

        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)
        abstract = netlist_from_spec(spec)
        abstract = _monotone_sort(abstract, "Foundation_1x1")
        nl = place(abstract, "Foundation_1x1")
        assert _count_inversions(nl) == 0

    def test_reversed_pins_minimized(self):
        """Reversed source-to-sink wiring ⇒ monotone sort + placer achieve 0 inversions.

        Machines are interchangeable (same type), so the placer reassigns
        them to eliminate the crossings that the reversed edges would cause.
        """
        from shapez2_tools.place import place

        abstract = {
            "nodes": [
                {"id": "src3", "type": SRC_TYPE, "kind": "platform_in"},
                {"id": "src2", "type": SRC_TYPE, "kind": "platform_in"},
                {"id": "src1", "type": SRC_TYPE, "kind": "platform_in"},
                {"id": "src0", "type": SRC_TYPE, "kind": "platform_in"},
                {"id": "m0", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "m1", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "m2", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "m3", "type": "RotatorHalfInternalVariant", "kind": "machine"},
                {"id": "sink3", "type": SINK_TYPE, "kind": "platform_out"},
                {"id": "sink2", "type": SINK_TYPE, "kind": "platform_out"},
                {"id": "sink1", "type": SINK_TYPE, "kind": "platform_out"},
                {"id": "sink0", "type": SINK_TYPE, "kind": "platform_out"},
            ],
            "edges": [
                ("src0", "m0"),
                ("m0", "sink0"),
                ("src1", "m1"),
                ("m1", "sink1"),
                ("src2", "m2"),
                ("m2", "sink2"),
                ("src3", "m3"),
                ("m3", "sink3"),
            ],
        }
        abstract = _monotone_sort(abstract, "Foundation_1x1")

        sources = [n for n in abstract["nodes"] if n["kind"] == "platform_in"]
        assert [n["id"] for n in sources] == ["src0", "src1", "src2", "src3"]

        nl = place(abstract, "Foundation_1x1")
        assert _count_inversions(nl) == 0


class TestQuotient:
    """WP-L: quotient + stamp for lane-uniform specs."""

    def test_quotient_isomorphic_to_direct(self):
        """Quotient+stamp lift ≅ direct route lift per floor; belt counts 3×."""
        spec = Spec(op="rotate_180", platform="Foundation_1x1", throughput=2)

        direct = synthesize(spec, layer=0)
        direct_nl = lift.trace_layer(direct, 0)

        quotient = synthesize_quotient(spec)

        for floor in range(3):
            floor_nl = lift.trace_layer(quotient, floor)
            assert lift.isomorphic(direct_nl, floor_nl), f"floor {floor} not isomorphic"

        direct_count = len(functional_entities(direct))
        quotient_count = len(functional_entities(quotient))
        assert quotient_count == direct_count * 3


# ---------------------------------------------------------------------------
# WP-M: row-based placement + feedback loop
# ---------------------------------------------------------------------------


class TestRowPlacement:
    """WP-M: machines snap to stage rows."""

    def test_stage_computation(self):
        """_compute_stages assigns correct depth from sources."""
        from shapez2_tools.place import _compute_stages

        abstract = netlist_from_spec(
            Spec(op=("rotate_cw", "rotate_cw"), platform="Foundation_1x1", throughput=2)
        )
        stages = _compute_stages(abstract)
        for nid, s in stages.items():
            if "_s0" in nid:
                assert s == 0, f"{nid} expected stage 0, got {s}"
            elif "_s1" in nid:
                assert s == 1, f"{nid} expected stage 1, got {s}"

    def test_same_stage_same_y(self):
        """2-stage spec ⇒ exactly 2 distinct machine y-values."""
        from shapez2_tools.place import _compute_stages, place

        spec = Spec(
            op=("rotate_cw", "rotate_cw"),
            platform="Foundation_1x1",
            throughput=2,
        )
        abstract = netlist_from_spec(spec)
        stages = _compute_stages(abstract)
        n_stages = max(stages.values()) + 1
        assert n_stages == 2

        abstract = _monotone_sort(abstract, spec.platform)
        nl = place(abstract, spec.platform)

        machine_ys = {pos[1] for pos, n in nl.nodes.items() if n.kind == "machine"}
        assert len(machine_ys) == n_stages, (
            f"expected {n_stages} distinct y-values, got {machine_ys}"
        )

    def test_half_destroy_throughput_3(self):
        """Half-destroy with throughput=3 synthesizes (the WP-D blocker)."""
        from shapez2_tools import interpret

        spec = Spec(op="half_destroy", platform="Foundation_1x1", throughput=3)
        result = synthesize(spec)
        assert lift.validate(result) == []

        nl = lift.trace_layer(result, 0)
        inputs = {
            p: Shape.parse("RuCuSuWu")
            for p, n in nl.nodes.items()
            if n.kind == "platform_in"
        }
        outputs = interpret.interpret(nl, inputs)
        expected = Shape.parse("RuCu----")
        assert all(s == expected for s in outputs.values())

    def test_diagonal_4pair_2x2_still_green(self):
        """Regression: 4-pair diagonal on 2×2 still synthesizes correctly."""
        from shapez2_tools import interpret

        spec = DiagonalSpec(pairs=4, platform="Foundation_2x2")
        result = synthesize_diagonal(spec)
        assert lift.validate(result) == []

        nl = lift.trace_layer(result, 0)
        assert len(nl.edges) == 16

        srcs = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "platform_in"],
            key=lambda pn: pn[0][0],
        )
        north = Shape.parse("Ru----Ru")
        south = Shape.parse("--RuRu--")
        inputs = {}
        for i, (pos, _) in enumerate(srcs):
            inputs[pos] = north if i % 2 == 0 else south

        outputs = interpret.interpret(nl, inputs)
        out_shapes = {str(s) for s in outputs.values()}
        assert "Ru--Ru--" in out_shapes
        assert "--Ru--Ru" in out_shapes
