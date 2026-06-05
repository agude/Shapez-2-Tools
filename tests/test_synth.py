"""WP-E: synthesis tests."""

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
