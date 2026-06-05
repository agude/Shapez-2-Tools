"""WP-E: synthesis tests."""

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.shapes import Shape
from shapez2_tools.synth import Spec, netlist_from_spec, synthesize
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

        assert len(by_kind["src"]) == 4
        assert len(by_kind["sink"]) == 4
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
            if n["kind"] == "src":
                assert len(out_edges[n["id"]]) == 2
            elif n["kind"] == "sink":
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

        assert len(by_kind["src"]) == 4
        assert len(by_kind["sink"]) == 4
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
            if n["kind"] == "src":
                assert len(out_edges[n["id"]]) == 1
            elif n["kind"] == "sink":
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

        assert len(by_kind["src"]) == 4
        assert len(by_kind["sink"]) == 4
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

        inputs = {p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "src"}
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
        inputs = {p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "src"}
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
        inputs = {p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "src"}
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
        inputs = {p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "src"}
        outputs = interpret.interpret(nl, inputs)

        expected = Shape.parse("WuRuCuSu")
        assert all(s == expected for s in outputs.values())

    @pytest.mark.xfail(reason="16 machines + fan patterns on 1x1 exceeds router capacity")
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
        inputs = {p: Shape.parse("RuCuSuWu") for p, n in nl.nodes.items() if n.kind == "src"}
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
            {"id": "src0", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
            {"id": "src1", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
            {"id": "src2", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
            {"id": "src3", "type": "BeltPortReceiverInternalVariant", "kind": "src"},
            {"id": "swap0", "type": "SwapperDefaultInternalVariant", "kind": "machine"},
            {"id": "swap1", "type": "SwapperDefaultInternalVariant", "kind": "machine"},
            {"id": "sink0", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
            {"id": "sink1", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
            {"id": "sink2", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
            {"id": "sink3", "type": "BeltPortSenderInternalVariant", "kind": "sink"},
        ]
        edges = [
            ("src0", "swap0"), ("src1", "swap0"),
            ("swap0", "sink0"), ("swap0", "sink1"),
            ("src2", "swap1"), ("src3", "swap1"),
            ("swap1", "sink2"), ("swap1", "sink3"),
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
            for dx, dy in fp:
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
            [(p, n) for p, n in nl.nodes.items() if n.kind == "src"],
            key=lambda pn: pn[0][0],
        )
        sinks = sorted(
            [(p, n) for p, n in nl.nodes.items() if n.kind == "sink"],
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
