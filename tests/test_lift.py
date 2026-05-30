"""Tests for the netlist lifter (Rung 1)."""

from collections import Counter
from pathlib import Path

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
QUARTER = REF / "quarter_rotate_180.spz2bp"
FULL = REF / "full_belt_rotate_180.spz2bp"
DESTROY = REF / "quarter_destroy_west_half.spz2bp"


class TestBeltModel:
    def test_routing_classification(self):
        assert lift.kind("BeltDefaultForwardInternalVariant") == "belt"
        assert lift.kind("Splitter1To2LInternalVariant") == "belt"
        assert lift.kind("Merger2To1LInternalVariantMirrored") == "belt"
        assert lift.kind("BeltPortReceiverInternalVariant") == "src"
        assert lift.kind("BeltPortSenderInternalVariant") == "sink"
        assert lift.kind("RotatorHalfInternalVariant") == "machine"

    def test_forward_belt_in_out_opposite(self):
        ins, outs = lift.routing_inout("BeltDefaultForwardInternalVariant", 3)
        assert ins == frozenset({lift.N}) and outs == frozenset({lift.S})

    def test_quarter_belt_graph_is_well_formed(self):
        assert lift.unmatched_legs(Blueprint.from_file(QUARTER), 0) == 0


class TestTrace:
    def test_recovers_rotator_quarter_netlist(self):
        nl = lift.trace_layer(Blueprint.from_file(QUARTER), 0)
        kinds = Counter(n.kind for n in nl.nodes.values())
        assert kinds["src"] == 4 and kinds["sink"] == 4 and kinds["machine"] == 8
        ek = lift.edge_kinds(nl)
        assert ek[("src", "machine")] == 8  # each input splits to two rotators
        assert ek[("machine", "sink")] == 8  # each rotator merges to an output

    def test_full_belt_is_four_quarters(self):
        bp = Blueprint.from_file(FULL)
        assert lift.unmatched_legs(bp, 0) == 0
        nl = lift.trace_layer(bp, 0)
        kinds = Counter(n.kind for n in nl.nodes.values())
        assert kinds["src"] == 16 and kinds["sink"] == 16 and kinds["machine"] == 32
        ek = lift.edge_kinds(nl)
        assert ek[("src", "machine")] == 32
        assert ek[("machine", "sink")] == 32


class TestJunctions:
    def test_half_destroyer_lifts_clean(self):
        # Exercises Splitter1To3 / Merger3To1: 4 inputs -> 12 half-cutters -> 4 out.
        bp = Blueprint.from_file(DESTROY)
        assert lift.unmatched_legs(bp, 0) == 0
        kinds = Counter(n.kind for n in lift.trace_layer(bp, 0).nodes.values())
        assert kinds == Counter({"machine": 12, "src": 4, "sink": 4})
