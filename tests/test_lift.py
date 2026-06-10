"""Tests for the netlist lifter (Rung 1) + hop tracing (WP-K)."""

from collections import Counter
from pathlib import Path

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
BLUEPRINTS = Path.home() / "Projects" / "shapez_2_blueprints"
HALF_SPLITTER = BLUEPRINTS / "UNFINISHED Half Splitter.spz2bp"
QUARTER = REF / "quarter_rotate_180.spz2bp"
FULL = REF / "full_belt_rotate_180.spz2bp"
DESTROY = REF / "quarter_destroy_west_half.spz2bp"
CUTTER = REF / "cutter_12_to_24.spz2bp"
SWAP = REF / "swap_diagonal.spz2bp"


class TestBeltModel:
    def test_routing_classification(self):
        assert lift.kind("BeltDefaultForwardInternalVariant") == "belt"
        assert lift.kind("Splitter1To2LInternalVariant") == "belt"
        assert lift.kind("Merger2To1LInternalVariantMirrored") == "belt"
        assert lift.kind("BeltPortReceiverInternalVariant") == "platform_in"
        assert lift.kind("BeltPortSenderInternalVariant") == "platform_out"
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
        assert kinds["platform_in"] == 4 and kinds["platform_out"] == 4 and kinds["machine"] == 8
        ek = lift.edge_kinds(nl)
        assert ek[("platform_in", "machine")] == 8  # each input splits to two rotators
        assert ek[("machine", "platform_out")] == 8  # each rotator merges to an output

    def test_full_belt_is_four_quarters(self):
        bp = Blueprint.from_file(FULL)
        assert lift.unmatched_legs(bp, 0) == 0
        nl = lift.trace_layer(bp, 0)
        kinds = Counter(n.kind for n in nl.nodes.values())
        assert kinds["platform_in"] == 16 and kinds["platform_out"] == 16 and kinds["machine"] == 32
        ek = lift.edge_kinds(nl)
        assert ek[("platform_in", "machine")] == 32
        assert ek[("machine", "platform_out")] == 32


class TestJunctions:
    def test_half_destroyer_lifts_clean(self):
        # Exercises Splitter1To3 / Merger3To1: 4 inputs -> 12 half-cutters -> 4 out.
        bp = Blueprint.from_file(DESTROY)
        assert lift.unmatched_legs(bp, 0) == 0
        kinds = Counter(n.kind for n in lift.trace_layer(bp, 0).nodes.values())
        assert kinds == Counter({"machine": 12, "platform_in": 4, "platform_out": 4})


class TestCutter:
    def test_footprint_is_one_entity_plus_output_only_cell(self):
        # Verified against data/reference/cutters_8_pinwheel.spz2bp: a cutter is
        # ONE entity spanning two cells -- anchor (1 input on its back, main
        # output on its front) + an output-only second cell on the front. The
        # second cell sits right of flow (Default) / left (Mirrored).
        fp = lift._machine_footprint("CutterDefaultInternalVariant", 0)
        assert fp[(0, 0, 0)] == (frozenset({lift.W}), frozenset({lift.E}))
        assert fp[(*lift.S, 0)] == (frozenset(), frozenset({lift.E}))  # right of flow
        mirrored = lift._machine_footprint("CutterDefaultInternalVariantMirrored", 0)
        assert mirrored[(*lift.N, 0)] == (frozenset(), frozenset({lift.E}))  # left of flow
        # The half-destroyer stays a single 1-in/1-out cell.
        half = lift._machine_footprint("CutterHalfInternalVariant", 0)
        assert half == {(0, 0, 0): (frozenset({lift.W}), frozenset({lift.E}))}

    def test_belts_routing_past_a_machine_are_not_inputs(self):
        # The dense 12->24 blueprint is 16 independent 1-in/2-out cutters per
        # floor -- NOT 8 Default+Mirrored "pairs". Belts that L-turn *past* an
        # output-only cell never connect (it has no input side), so the floor
        # lifts with zero unmatched legs and every cutter has in-degree 1.
        bp = Blueprint.from_file(CUTTER)
        assert lift.unmatched_legs(bp, 0) == 0
        nl = lift.trace_layer(bp, 0)
        cutters = {p for p, n in nl.nodes.items() if "Cutter" in n.type and "Half" not in n.type}
        assert len(cutters) == 16
        indeg = Counter(b for _a, b in nl.edges if b in cutters)
        outdeg = Counter(a for a, _b in nl.edges if a in cutters)
        assert set(indeg.values()) == {1} and len(indeg) == 16  # one input, no pass-by
        assert set(outdeg.values()) == {2} and len(outdeg) == 16  # two outputs each


class TestSwapper:
    def test_footprint_is_two_through_cells(self):
        # Like the cutter, a swapper is one entity + a second cell to the right
        # of flow (Default) / left (Mirrored) -- but BOTH cells are in-back /
        # out-front (2-in/2-out). Confirmed by Swap Diagonal lifting at 0
        # unmatched legs (swappers as output-only second cell does not).
        through = (frozenset({lift.W}), frozenset({lift.E}))
        fp = lift._machine_footprint("HalvesSwapperDefaultInternalVariant", 0)
        assert fp == {(0, 0, 0): through, (*lift.S, 0): through}  # 2nd cell right of flow
        mirrored = lift._machine_footprint("HalvesSwapperDefaultInternalVariantMirrored", 0)
        assert mirrored == {(0, 0, 0): through, (*lift.N, 0): through}  # left of flow

    def test_swap_diagonal_lifts_clean(self):
        # The diagonal extractor: 32 swappers fed two shapes each, swapping west
        # halves. The whole floor lifts with zero unmatched legs and every
        # swapper is 2-in/2-out.
        bp = Blueprint.from_file(SWAP)
        assert lift.unmatched_legs(bp, 0) == 0
        nl = lift.trace_layer(bp, 0)
        swappers = {p for p, n in nl.nodes.items() if "Swapper" in n.type}
        assert len(swappers) == 32
        indeg = Counter(b for _a, b in nl.edges if b in swappers)
        outdeg = Counter(a for a, _b in nl.edges if a in swappers)
        assert set(indeg.values()) == {2} and len(indeg) == 32  # two inputs each
        assert set(outdeg.values()) == {2} and len(outdeg) == 32  # two outputs each


STACK_STRAIGHT = REF / "stackers_straight_4.spz2bp"
STACK_BENT = REF / "stackers_bent_8.spz2bp"


class TestStacker:
    def test_footprint_vertical_input(self):
        """The stacker's secondary input is one floor up at the anchor."""
        # StackerStraight: in from back, out forward, L+1 in from back.
        fp = lift._machine_footprint("StackerStraightInternalVariant", 0)
        assert fp[(0, 0, 0)] == (frozenset({lift.W}), frozenset({lift.E}))
        assert fp[(0, 0, 1)] == (frozenset({lift.W}), frozenset())

        # StackerDefault: in from back, out RIGHT of flow, L+1 in from back.
        fp = lift._machine_footprint("StackerDefaultInternalVariant", 0)
        assert fp[(0, 0, 0)] == (frozenset({lift.W}), frozenset({lift.S}))
        assert fp[(0, 0, 1)] == (frozenset({lift.W}), frozenset())

        # Mirrored: out LEFT of flow.
        fp = lift._machine_footprint("StackerDefaultInternalVariantMirrored", 0)
        assert fp[(0, 0, 0)] == (frozenset({lift.W}), frozenset({lift.N}))
        assert fp[(0, 0, 1)] == (frozenset({lift.W}), frozenset())

    def test_footprint_rotated(self):
        """Cross-floor input direction rotates with the machine."""
        fp = lift._machine_footprint("StackerStraightInternalVariant", 1)
        # R=1: back=S, fwd=N.
        assert fp[(0, 0, 0)] == (frozenset({lift.S}), frozenset({lift.N}))
        assert fp[(0, 0, 1)] == (frozenset({lift.S}), frozenset())

    def test_stacker_nodes_in_single_layer_trace(self):
        """trace_layer finds 4 stacker nodes on L0 (open fixture, no edges)."""
        bp = Blueprint.from_file(STACK_STRAIGHT)
        nl = lift.trace_layer(bp, 0)
        stackers = {p for p, n in nl.nodes.items() if "Stacker" in n.type}
        assert len(stackers) == 4

    def test_stacker_cross_floor_trace_synthetic(self):
        """Synthetic stacker with ports on both floors: 2-in / 1-out."""
        entries = [
            {"X": 5, "Y": 7, "T": "BeltPortReceiverInternalVariant"},
            {"X": 6, "Y": 7, "T": "BeltDefaultForwardInternalVariant"},
            {"X": 7, "Y": 7, "T": "BeltDefaultForwardInternalVariant"},
            {"X": 8, "Y": 7, "T": "StackerStraightInternalVariant"},
            {"X": 9, "Y": 7, "T": "BeltDefaultForwardInternalVariant"},
            {"X": 10, "Y": 7, "T": "BeltPortSenderInternalVariant"},
            {"X": 6, "Y": 7, "L": 1, "T": "BeltPortReceiverInternalVariant"},
            {"X": 7, "Y": 7, "L": 1, "T": "BeltDefaultForwardInternalVariant"},
        ]
        data = {
            "V": 1137,
            "BP": {
                "$type": "Island",
                "Entries": [{"T": "Foundation_1x1", "B": {"Entries": entries}}],
                "Icon": {"Data": []},
            },
        }
        bp = Blueprint(data)
        nl = lift.trace(bp)
        stacker_key = (8, 7, 0)
        assert "Stacker" in nl.nodes[stacker_key].type
        indeg = sum(1 for _a, b in nl.edges if b == stacker_key)
        outdeg = sum(1 for a, _b in nl.edges if a == stacker_key)
        assert indeg == 2  # L0 primary + L1 secondary
        assert outdeg == 1

    def test_stacker_cross_floor_trace_finds_all_nodes(self):
        """3-D trace finds all stackers across both open fixtures."""
        for name, count in [("stackers_straight_4.spz2bp", 4), ("stackers_bent_8.spz2bp", 8)]:
            bp = Blueprint.from_file(REF / name)
            nl = lift.trace(bp)
            stackers = {p for p, n in nl.nodes.items() if "Stacker" in n.type}
            assert len(stackers) == count, f"{name}: expected {count}, got {len(stackers)}"


# ---------------------------------------------------------------------------
# WP-K: hop tracing (launcher/catcher pairs)
# ---------------------------------------------------------------------------


class TestHopPairing:
    """Interior hop endpoint detection and pairing."""

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_hop_pairing_half_splitter(self):
        """All 145 interior hop pairs in the Half Splitter resolve."""
        bp = Blueprint.from_file(HALF_SPLITTER)
        port_positions = lift._platform_port_positions(bp)
        pairs = lift._resolve_hops(bp, 0, port_positions)
        assert len(pairs) == 145

    @pytest.mark.skipif(not HALF_SPLITTER.exists(), reason="Half Splitter not found")
    def test_hop_contraction_half_splitter(self):
        """Hop-contracted Half Splitter: 16 sources, 64 cutters, 32 sinks."""
        bp = Blueprint.from_file(HALF_SPLITTER)
        nl = lift.trace_layer(bp, 0, contract_hops=True)

        by_kind = Counter(n.kind for n in nl.nodes.values())
        assert by_kind["platform_in"] == 16
        assert by_kind["machine"] == 64
        assert by_kind["platform_out"] == 32

    def test_hop_contraction_swap_diagonal(self):
        """Hop-contracted swap_diagonal: 8 sources, 80 machines, 8 sinks."""
        bp = Blueprint.from_file(SWAP)
        nl = lift.trace_layer(bp, 0, contract_hops=True)

        by_kind = Counter(n.kind for n in nl.nodes.values())
        assert by_kind["platform_in"] == 8
        assert by_kind["machine"] == 80
        assert by_kind["platform_out"] == 8

    def test_hop_contraction_no_hops_unchanged(self):
        """contract_hops=True on a blueprint without hops gives the same result."""
        bp = Blueprint.from_file(QUARTER)
        nl_default = lift.trace_layer(bp, 0)
        nl_hops = lift.trace_layer(bp, 0, contract_hops=True)

        assert len(nl_default.nodes) == len(nl_hops.nodes)
        assert len(nl_default.edges) == len(nl_hops.edges)
        assert lift.isomorphic(nl_default, nl_hops)

    def test_swap_diagonal_hop_pairs(self):
        """swap_diagonal has 18 interior hop pairs (36 endpoints)."""
        bp = Blueprint.from_file(SWAP)
        port_positions = lift._platform_port_positions(bp)
        pairs = lift._resolve_hops(bp, 0, port_positions)
        assert len(pairs) == 18
