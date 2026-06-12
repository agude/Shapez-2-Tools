"""WP-J: lift calibration — floors + lifts as cross-floor routing."""

from collections import Counter
from pathlib import Path

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.pathfinder import (
    Cell,
    Net,
    RoutingGraph,
    _cell_to_entity,
    _lift_emit_table,
    pathfinder_route,
)

REF = Path(__file__).resolve().parent.parent / "data" / "reference"
BALANCER = REF / "balancer_12_to_12.spz2bp"

N, S, E, W = lift.N, lift.S, lift.E, lift.W


class TestLiftInout:
    """Unit tests for the lift calibration table."""

    def test_lift_classified_as_lift(self):
        assert lift.kind("Lift1UpForwardInternalVariant") == "lift"
        assert lift.kind("Lift2DownLeftInternalVariantMirrored") == "lift"
        assert lift.kind("Lift1DownBackwardInternalVariant") == "lift"

    def test_not_matched_by_routing_inout(self):
        assert lift.routing_inout("Lift1UpLeftInternalVariant", 0) is None
        assert lift.routing_inout("Lift2DownForwardInternalVariant", 0) is None

    @pytest.mark.parametrize(
        "variant, r, expected_ins, expected_outs, expected_delta",
        [
            ("Lift1UpForwardInternalVariant", 0, {W}, {E}, 1),
            ("Lift1UpBackwardInternalVariant", 0, {W}, {W}, 1),
            ("Lift1UpLeftInternalVariant", 0, {W}, {S}, 1),
            ("Lift1UpLeftInternalVariantMirrored", 0, {W}, {N}, 1),
            ("Lift1DownForwardInternalVariant", 0, {W}, {E}, -1),
            ("Lift1DownBackwardInternalVariant", 0, {W}, {W}, -1),
            ("Lift1DownLeftInternalVariant", 0, {W}, {S}, -1),
            ("Lift1DownLeftInternalVariantMirrored", 0, {W}, {N}, -1),
            ("Lift2UpForwardInternalVariant", 0, {W}, {E}, 2),
            ("Lift2DownForwardInternalVariant", 0, {W}, {E}, -2),
            ("Lift2UpLeftInternalVariant", 0, {W}, {S}, 2),
            ("Lift2DownLeftInternalVariantMirrored", 0, {W}, {N}, -2),
        ],
    )
    def test_lift_inout_r0(self, variant, r, expected_ins, expected_outs, expected_delta):
        result = lift.lift_inout(variant, r)
        assert result is not None
        ins, outs, delta = result
        assert ins == frozenset(expected_ins)
        assert outs == frozenset(expected_outs)
        assert delta == expected_delta

    def test_lift_inout_rotated(self):
        ins, outs, delta = lift.lift_inout("Lift1UpForwardInternalVariant", 1)
        assert ins == frozenset({S})
        assert outs == frozenset({N})
        assert delta == 1

    def test_lift_inout_non_lift_returns_none(self):
        assert lift.lift_inout("BeltDefaultForwardInternalVariant", 0) is None
        assert lift.lift_inout("RotatorHalfInternalVariant", 0) is None

    def test_all_16_variants_recognised(self):
        bases = ["Forward", "Backward", "Left"]
        for prefix in ["Lift1", "Lift2"]:
            for direction in ["Up", "Down"]:
                for exit_dir in bases:
                    variant = f"{prefix}{direction}{exit_dir}InternalVariant"
                    assert lift.lift_inout(variant, 0) is not None, variant
                    mirrored = f"{prefix}{direction}{exit_dir}InternalVariantMirrored"
                    if exit_dir == "Left":
                        assert lift.lift_inout(mirrored, 0) is not None, mirrored


class TestLiftFootprint:
    def test_lift1_up_has_two_cells(self):
        fp = lift._lift_footprint("Lift1UpForwardInternalVariant", 0)
        assert fp is not None
        assert (0, 0, 0) in fp
        assert (0, 0, 1) in fp
        assert len(fp) == 2

    def test_lift2_down_has_three_cells(self):
        fp = lift._lift_footprint("Lift2DownForwardInternalVariant", 0)
        assert fp is not None
        assert (0, 0, 0) in fp
        assert (0, 0, -1) in fp
        assert (0, 0, -2) in fp
        assert len(fp) == 3

    def test_input_at_dl0_output_at_delta(self):
        fp = lift._lift_footprint("Lift1UpLeftInternalVariant", 0)
        ins_0, outs_0 = fp[(0, 0, 0)]
        assert ins_0 == frozenset({W})
        assert outs_0 == frozenset()
        ins_1, outs_1 = fp[(0, 0, 1)]
        assert ins_1 == frozenset()
        assert outs_1 == frozenset({S})


class TestBalancer:
    """The 12-to-12 Balancer: a pure-routing + lifts blueprint."""

    def test_unmatched_legs_all_floors(self):
        bp = Blueprint.from_file(BALANCER)
        for layer in range(3):
            assert lift.unmatched_legs(bp, layer) == 0, f"layer {layer}"

    def test_3d_trace_only_ports(self):
        bp = Blueprint.from_file(BALANCER)
        nl = lift.trace(bp)
        kinds = Counter(n.kind for n in nl.nodes.values())
        assert kinds["platform_in"] == 16
        assert kinds["platform_out"] == 16
        assert "machine" not in kinds
        assert "lift" not in kinds

    def test_3d_trace_edges_input_to_output(self):
        bp = Blueprint.from_file(BALANCER)
        nl = lift.trace(bp)
        ek = lift.edge_kinds(nl)
        assert set(ek.keys()) == {("platform_in", "platform_out")}
        assert sum(ek.values()) > 0

    def test_3d_trace_uses_all_floors(self):
        bp = Blueprint.from_file(BALANCER)
        nl = lift.trace(bp)
        floors = {key[2] for key in nl.nodes}
        assert floors == {0, 1, 2}


class TestLiftEmitTable:
    def test_all_16_variants_in_table(self):
        table = _lift_emit_table()
        assert len(table) > 0
        deltas_found = {delta for _, _, delta in table}
        assert deltas_found >= {-2, -1, 1, 2}

    def test_roundtrip_lift_inout_to_emit(self):
        """Every (ins, outs, delta) from lift_inout maps back to a variant."""
        table = _lift_emit_table()
        bases = ["Forward", "Backward", "Left"]
        for prefix in ["Lift1", "Lift2"]:
            for direction in ["Up", "Down"]:
                for exit_dir in bases:
                    for suffix in ["InternalVariant", "InternalVariantMirrored"]:
                        if exit_dir != "Left" and suffix == "InternalVariantMirrored":
                            continue
                        variant = f"{prefix}{direction}{exit_dir}{suffix}"
                        for r in range(4):
                            info = lift.lift_inout(variant, r)
                            if info is None:
                                continue
                            ins, outs, delta = info
                            assert (ins, outs, delta) in table, (
                                f"{variant} R={r} → ({ins}, {outs}, {delta}) missing"
                            )


class TestCrossingNets:
    """Two nets that topologically must cross on one floor, resolved via lift."""

    def _build_crossing(self):
        """5×5 grid on 2 floors. Net A: west→east, net B: south→north.
        Paths cross at the center — only a lift can resolve it.
        """
        passable: set[Cell] = set()
        for x in range(5):
            for y in range(5):
                for ly in range(2):
                    passable.add((x, y, ly))

        net_a = Net(net_id=0, kind="fanout", root=(0, 2, 0), terminals=[(4, 2, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(2, 0, 0), terminals=[(2, 4, 0)])
        return [net_a, net_b], passable

    def test_crossing_fails_without_lift(self):
        nets, passable = self._build_crossing()
        graph = RoutingGraph(passable=passable, lift_enabled=False)
        ok = pathfinder_route(nets, graph, raise_on_failure=False)
        assert not ok

    def test_crossing_succeeds_with_lift(self):
        nets, passable = self._build_crossing()
        graph = RoutingGraph(passable=passable, lift_enabled=True)
        ok = pathfinder_route(nets, graph, raise_on_failure=False)
        assert ok

    def test_crossing_uses_lift_edge(self):
        nets, passable = self._build_crossing()
        graph = RoutingGraph(passable=passable, lift_enabled=True)
        pathfinder_route(nets, graph)
        lift_count = sum(len(n.lift_edges) for n in nets)
        assert lift_count >= 2

    def test_lift_emit_produces_lift_entity(self):
        """Route crossing nets, emit lift entities → correct lift variant."""
        nets, passable = self._build_crossing()
        graph = RoutingGraph(passable=passable, lift_enabled=True)
        pathfinder_route(nets, graph)

        entities = []
        roots_and_terms = set()
        for net in nets:
            roots_and_terms.add(net.root)
            roots_and_terms.update(net.terminals)
        for net in nets:
            for cell in sorted(net.tree_cells, key=lambda c: (c[2], c[1], c[0])):
                if cell in roots_and_terms:
                    continue
                ent = _cell_to_entity(
                    cell, net.tree_edges,
                    hop_edges=net.hop_edges,
                    lift_edges=net.lift_edges,
                )
                if ent is not None:
                    entities.append(ent)
        lift_ents = [e for e in entities if "Lift" in e.type]
        assert len(lift_ents) >= 1
        for ent in lift_ents:
            assert lift.lift_inout(ent.type, ent.rotation) is not None
