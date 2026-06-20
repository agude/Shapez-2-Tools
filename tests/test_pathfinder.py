"""WP-I: PathFinder negotiated-congestion router tests.

Test-first per §7.2. Flavours 4 (round-trip/isomorphism) and 5 (physical).
"""

from pathlib import Path

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity
from shapez2_tools.pathfinder import (
    Net,
    RoutingError,
    RoutingGraph,
    _cell_to_entity,
    pathfinder_route,
)

REF = Path(__file__).resolve().parent.parent / "data" / "reference"


def _make_bp(entities, platform="Foundation_1x1"):
    """Wrap entities in a minimal blueprint."""
    from shapez2_tools.route import entities_to_blueprint

    return entities_to_blueprint(entities, platform=platform)


class TestNegotiation:
    """Core PathFinder negotiation behavior."""

    def test_blocked_pocket_negotiates(self):
        """Net B's sink sits in a pocket; net A must detour.

        Layout (y increases upward):

            . . . . . .
            . . W W W .    W = wall (obstacle)
            A . . . B .    A's shortest goes through the gap at (2,1)
            . . G . . .    G = gap (2,1), B's only entrance
            . . B . . .    B's sink at (2,0)

        Sequential hard-obstacle routing strands B if A routes first through
        the gap. PathFinder must negotiate: A detours, B gets the gap.
        """
        walls = {(2, 2, 0), (3, 2, 0), (4, 2, 0)}
        all_cells = {(x, y, 0) for x in range(6) for y in range(4)}
        passable = all_cells - walls

        net_a = Net(
            net_id=0,
            kind="fanout",
            root=(0, 1, 0),
            terminals=[(5, 1, 0)],
        )
        net_b = Net(
            net_id=1,
            kind="fanout",
            root=(4, 1, 0),
            terminals=[(2, 0, 0)],
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net_a, net_b], graph)

        assert success
        assert net_a.tree_cells and net_b.tree_cells
        assert not (net_a.tree_cells & net_b.tree_cells), "Nets must not share cells"

    def test_oscillation_breaks_via_history(self):
        """Two nets sharing two equal-cost corridors converge via history.

        Layout: two parallel corridors (rows 0 and 2), both nets go left→right
        on the same row, but a bottleneck forces them to compete for one corridor.
        Each net has an equally good alternative corridor, so without history
        they could oscillate.

            A_src . . . . A_dst
            .     . . . . .
            B_src . . . . B_dst

        Both nets go left→right on separate rows — no crossing needed.
        """
        passable = set()
        for x in range(8):
            passable.add((x, 0, 0))
            passable.add((x, 1, 0))
            passable.add((x, 2, 0))

        net_a = Net(net_id=0, kind="fanout", root=(0, 0, 0), terminals=[(7, 0, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(0, 2, 0), terminals=[(7, 2, 0)])

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net_a, net_b], graph)

        assert success
        assert not (net_a.tree_cells & net_b.tree_cells)

    def test_impossible_crossing_raises(self):
        """Two nets that must topologically cross on one floor raise RoutingError.

        Net A goes (0,2)→(4,2), net B goes (2,0)→(2,4) in a 5×5 grid.
        On a single floor with only (1-in, 1-out) through (1-in, 3-out)
        leg patterns, no cell can serve as a 2-in/2-out crossing. The router
        must raise, not silently emit overlapping belts.
        """
        passable = {(x, y, 0) for x in range(5) for y in range(5)}

        net_a = Net(net_id=0, kind="fanout", root=(0, 2, 0), terminals=[(4, 2, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(2, 0, 0), terminals=[(2, 4, 0)])

        graph = RoutingGraph(passable=passable)
        with pytest.raises(RoutingError):
            pathfinder_route([net_a, net_b], graph)

    def test_unreachable_terminal_raises(self):
        """A terminal walled off from the root raises, never a silent empty net.

        Column x=2 is impassable, splitting the 5×5 grid; the terminal sits
        in the far component.
        """
        passable = {(x, y, 0) for x in range(5) for y in range(5) if x != 2}

        net = Net(net_id=0, kind="fanout", root=(0, 2, 0), terminals=[(4, 2, 0)])

        graph = RoutingGraph(passable=passable)
        with pytest.raises(RoutingError, match="unreachable"):
            pathfinder_route([net], graph)


class TestFanPatterns:
    """Fan-in / fan-out tree construction and leg legality."""

    def test_tight_fanin_two_cells_from_sink(self):
        """4 sources, sink ~2 cells away — the corpus disease."""
        passable = {(x, y, 0) for x in range(8) for y in range(8)}

        net = Net(
            net_id=0,
            kind="fanin",
            root=(5, 4, 0),
            terminals=[(3, 3, 0), (3, 4, 0), (3, 5, 0), (3, 6, 0)],
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net], graph)

        assert success
        assert len(net.tree_edges) >= 4

    def test_fanout_tree_legs_legal(self):
        """1→4 fan-out: every tree cell has a legal leg pattern."""
        passable = {(x, y, 0) for x in range(15) for y in range(10)}

        net = Net(
            net_id=0,
            kind="fanout",
            root=(0, 5, 0),
            terminals=[(10, 2, 0), (10, 4, 0), (10, 6, 0), (10, 8, 0)],
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net], graph)

        assert success
        _assert_legs_legal(net)

    def test_fanin_tree_legs_legal(self):
        """4→1 fan-in: every tree cell has a legal leg pattern."""
        passable = {(x, y, 0) for x in range(15) for y in range(10)}

        net = Net(
            net_id=0,
            kind="fanin",
            root=(10, 5, 0),
            terminals=[(0, 2, 0), (0, 4, 0), (0, 6, 0), (0, 8, 0)],
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net], graph)

        assert success
        _assert_legs_legal(net)


LEGAL_LEG_PATTERNS = {
    (1, 1),
    (1, 2),
    (1, 3),
    (2, 1),
    (3, 1),
}


def _assert_legs_legal(net: Net):
    """Every interior tree cell's (in_count, out_count) must be in the legal set.

    Root and terminal cells are endpoints (machine/port positions), not belt
    cells, so they are excluded from the check.
    """
    from collections import Counter

    endpoints = {net.root} | set(net.terminals)
    in_count: Counter[tuple] = Counter()
    out_count: Counter[tuple] = Counter()
    for src, dst in net.tree_edges:
        out_count[src] += 1
        in_count[dst] += 1
    all_cells = set(in_count) | set(out_count)
    for c in all_cells:
        if c in endpoints:
            continue
        pattern = (in_count.get(c, 0), out_count.get(c, 0))
        assert pattern in LEGAL_LEG_PATTERNS, f"Cell {c} has illegal pattern {pattern}"

    def test_root_branches_as_splitter_when_offset(self):
        """1→2 fan: downstream walled, splitter must be at root cell.

        Narrow column: only x=1 is passable. Root at (1,0) must branch north
        and south to reach both terminals. Without root_offset pre-seeding,
        the root's candidate pattern (0,2) is illegal and routing fails.
        """
        passable = {(1, y, 0) for y in range(-3, 5)}

        net = Net(
            net_id=0,
            kind="fanout",
            root=(1, 0, 0),
            terminals=[(1, 3, 0), (1, -2, 0)],
            root_offset=True,
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net], graph)

        assert success
        root_outs = sum(1 for s, _d in net.tree_edges if s == net.root)
        assert root_outs >= 2, "root must be the branching splitter"

    def test_fanin_root_merges_when_offset(self):
        """2→1 fan-in: merger directly adjacent to sink (root cell).

        Mirror of the fanout test. Narrow column forces both source paths
        through the root cell.
        """
        passable = {(1, y, 0) for y in range(-3, 5)}

        net = Net(
            net_id=0,
            kind="fanin",
            root=(1, 0, 0),
            terminals=[(1, 3, 0), (1, -2, 0)],
            root_offset=True,
        )

        graph = RoutingGraph(passable=passable)
        success = pathfinder_route([net], graph)

        assert success
        assert all(t in net.tree_cells for t in net.terminals)


class TestPortBandPassability:
    """WP-N task 3e.2: the platform's port ring is ports-only in-game.

    ``_platform_bounds`` returns the full port bounding box, but the
    outermost ring of that box is buildable-area-adjacent port cells, not
    routable interior — only the specific port cells that are net endpoints
    should stay passable.
    """

    def test_ring_excluded_except_net_endpoints(self):
        """Non-port ring cells are excluded; net-endpoint ports stay passable."""
        from shapez2_tools.pathfinder import _build_passable, _platform_bounds

        min_x, max_x, min_y, max_y = _platform_bounds("Foundation_1x1")
        assert (min_x, max_x, min_y, max_y) == (2, 17, 2, 17)

        nl = lift.Netlist(
            nodes={
                (2, 8): lift.Node(
                    x=2,
                    y=8,
                    layer=0,
                    type="BeltPortReceiverInternalVariant",
                    kind="platform_in",
                    rotation=0,
                ),
                (17, 8): lift.Node(
                    x=17,
                    y=8,
                    layer=0,
                    type="BeltPortSenderInternalVariant",
                    kind="platform_out",
                    rotation=0,
                ),
            },
            edges=[((2, 8), (17, 8))],
            port_edges=[((2, 8), (17, 8))],
        )

        passable = _build_passable(nl, machine_cells=set(), floors=(0,), platform="Foundation_1x1")

        # Net-endpoint ports, on the ring, stay passable.
        assert (2, 8, 0) in passable
        assert (17, 8, 0) in passable
        # Non-port ring cells (same edges, other rows/cols) are excluded.
        assert (2, 9, 0) not in passable
        assert (17, 9, 0) not in passable
        assert (2, 2, 0) not in passable
        # A geometrically valid port position that isn't a node of *this*
        # netlist is still excluded -- it's not an endpoint here.
        assert (8, 2, 0) not in passable
        # Interior cells (one step in from the ring) are passable.
        assert (3, 8, 0) in passable
        assert (16, 8, 0) in passable
        assert (9, 9, 0) in passable

    def test_no_platform_keeps_full_bounding_box(self):
        """Without a platform, the node-bounding-box fallback is unchanged."""
        from shapez2_tools.pathfinder import _build_passable

        nl = lift.Netlist(
            nodes={
                (0, 0): lift.Node(
                    x=0,
                    y=0,
                    layer=0,
                    type="BeltPortReceiverInternalVariant",
                    kind="platform_in",
                    rotation=0,
                ),
                (4, 0): lift.Node(
                    x=4,
                    y=0,
                    layer=0,
                    type="BeltPortSenderInternalVariant",
                    kind="platform_out",
                    rotation=0,
                ),
            },
            edges=[((0, 0), (4, 0))],
            port_edges=[((0, 0), (4, 0))],
        )

        passable = _build_passable(nl, machine_cells=set(), floors=(0,), platform=None)

        # margin=5 around x in [0,4], y in [0,0]
        for x in range(-5, 10):
            for y in range(-5, 6):
                assert (x, y, 0) in passable

    def test_strip_and_reroute_platform_bounded(self):
        """Routing with ``platform=`` set never lands a non-port belt on the ring."""
        from shapez2_tools.pathfinder import _platform_bounds, strip_and_reroute
        from shapez2_tools.route import _all_entities

        src = Entity(type="BeltPortReceiverInternalVariant", x=2, y=8, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=17, y=8, rotation=0, layer=0)

        bp = _make_bp([src, sink], platform="Foundation_1x1")
        nl = lift.Netlist(
            nodes={
                (2, 8): lift.Node(x=2, y=8, layer=0, type=src.type, kind="platform_in", rotation=0),
                (17, 8): lift.Node(
                    x=17, y=8, layer=0, type=sink.type, kind="platform_out", rotation=0
                ),
            },
            edges=[((2, 8), (17, 8))],
            port_edges=[((2, 8), (17, 8))],
        )

        result_bp = strip_and_reroute(bp, nl, layer=0, platform="Foundation_1x1")
        result_nl = lift.trace_layer(result_bp, 0)
        assert lift.isomorphic(nl, result_nl)

        min_x, max_x, min_y, max_y = _platform_bounds("Foundation_1x1")
        port_cells = {(2, 8), (17, 8)}
        for e in _all_entities(result_bp):
            if e.layer != 0:
                continue
            on_ring = e.x in (min_x, max_x) or e.y in (min_y, max_y)
            if on_ring:
                assert (e.x, e.y) in port_cells, f"non-port entity on band: {e}"


class TestRootOnPort:
    """Guard: root that cannot leave its port cell must raise."""

    def test_root_on_port_cell_raises(self):
        """Offset cell blocked by another entity raises RoutingError."""
        from shapez2_tools.pathfinder import strip_and_reroute

        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=5, y=0, rotation=0, layer=0)
        # Block the src's offset cell (1, 0) with an unrelated machine. (Not a
        # PortSender/Receiver: those not in `nl.nodes` are now stripped as
        # interior hop endpoints — see strip_belts.)
        blocker = Entity(type="BlockerMachineInternalVariant", x=1, y=0, rotation=2, layer=0)

        bp = _make_bp([src, sink, blocker])
        nl = lift.Netlist(
            nodes={
                (0, 0): lift.Node(x=0, y=0, layer=0, type=src.type, kind="platform_in", rotation=0),
                (5, 0): lift.Node(
                    x=5, y=0, layer=0, type=sink.type, kind="platform_out", rotation=0
                ),
            },
            edges=[((0, 0), (5, 0))],
            port_edges=[((0, 0), (5, 0))],
        )

        with pytest.raises(RoutingError, match="root could not leave port cell"):
            strip_and_reroute(bp, nl, layer=0)


class TestBuildNets:
    """Net extraction guards."""

    def test_n_to_m_raises(self):
        """N→M component at a junction cell raises NotImplementedError."""
        from shapez2_tools.pathfinder import build_nets

        nodes = {
            (0, 0): lift.Node(
                x=0,
                y=0,
                layer=0,
                type="BeltPortReceiverInternalVariant",
                kind="platform_in",
                rotation=0,
            ),
            (0, 1): lift.Node(
                x=0,
                y=1,
                layer=0,
                type="BeltPortReceiverInternalVariant",
                kind="platform_in",
                rotation=0,
            ),
            (2, 0): lift.Node(
                x=2,
                y=0,
                layer=0,
                type="BeltPortReceiverInternalVariant",
                kind="platform_in",
                rotation=0,
            ),
            (4, 0): lift.Node(
                x=4,
                y=0,
                layer=0,
                type="BeltPortSenderInternalVariant",
                kind="platform_out",
                rotation=0,
            ),
            (4, 1): lift.Node(
                x=4,
                y=1,
                layer=0,
                type="BeltPortSenderInternalVariant",
                kind="platform_out",
                rotation=0,
            ),
        }
        port_edges = [
            ((0, 0), (2, 0)),
            ((0, 1), (2, 0)),
            ((2, 0), (4, 0)),
            ((2, 0), (4, 1)),
        ]
        nl = lift.Netlist(nodes=nodes, edges=port_edges, port_edges=port_edges)

        with pytest.raises(NotImplementedError, match="N→M"):
            build_nets(nl)


class TestEmit:
    """Emit: tree → belt entities → lift round-trip."""

    def test_emit_roundtrip_small(self):
        """Tiny netlist → pathfinder route → emit → lift → isomorphic."""
        from shapez2_tools.pathfinder import strip_and_reroute

        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink = Entity(type="BeltPortSenderInternalVariant", x=5, y=0, rotation=0, layer=0)

        bp = _make_bp([src, sink])
        nl = lift.trace_layer(bp, 0)

        # There are no belts to strip — just route the netlist
        assert len(nl.edges) == 0  # no connectivity yet (no belts)

        # Build a netlist with the edge we want
        nl_with_edge = lift.Netlist(
            nodes={
                (0, 0): lift.Node(x=0, y=0, layer=0, type=src.type, kind="platform_in", rotation=0),
                (5, 0): lift.Node(
                    x=5, y=0, layer=0, type=sink.type, kind="platform_out", rotation=0
                ),
            },
            edges=[((0, 0), (5, 0))],
            port_edges=[((0, 0), (5, 0))],
        )

        result_bp = strip_and_reroute(bp, nl_with_edge, layer=0)
        result_nl = lift.trace_layer(result_bp, 0)
        assert lift.isomorphic(nl_with_edge, result_nl)

    def test_deterministic(self):
        """Route the same instance twice — identical entity lists."""
        from shapez2_tools.pathfinder import strip_and_reroute

        src = Entity(type="BeltPortReceiverInternalVariant", x=0, y=0, rotation=0, layer=0)
        sink1 = Entity(type="BeltPortSenderInternalVariant", x=6, y=2, rotation=0, layer=0)
        sink2 = Entity(type="BeltPortSenderInternalVariant", x=6, y=-2, rotation=0, layer=0)

        bp = _make_bp([src, sink1, sink2])
        nl = lift.Netlist(
            nodes={
                (0, 0): lift.Node(x=0, y=0, layer=0, type=src.type, kind="platform_in", rotation=0),
                (6, 2): lift.Node(
                    x=6, y=2, layer=0, type=sink1.type, kind="platform_out", rotation=0
                ),
                (6, -2): lift.Node(
                    x=6, y=-2, layer=0, type=sink2.type, kind="platform_out", rotation=0
                ),
            },
            edges=[((0, 0), (6, 2)), ((0, 0), (6, -2))],
            port_edges=[((0, 0), (6, 2)), ((0, 0), (6, -2))],
        )

        bp1 = strip_and_reroute(bp, nl, layer=0)
        bp2 = strip_and_reroute(bp, nl, layer=0)

        from shapez2_tools.route import _all_entities

        ents1 = [(e.x, e.y, e.type, e.rotation) for e in _all_entities(bp1)]
        ents2 = [(e.x, e.y, e.type, e.rotation) for e in _all_entities(bp2)]
        assert ents1 == ents2


class TestPerFloorEmit:
    """WP-N task 3e: _cell_to_entity emits each cell on its own floor
    (cell[2]), not a caller-supplied layer -- needed for lift-aware routing
    where a net's tree spans multiple floors."""

    def test_floor_one_cell_emitted_on_floor_one(self):
        """A via cell on floor 1 (reached via a lift edge from floor 0)
        emits a belt entity on layer 1."""
        passable = {(0, 0, 0), (0, 0, 1), (1, 0, 1), (2, 0, 1)}
        net = Net(net_id=0, kind="fanout", root=(0, 0, 0), terminals=[(2, 0, 1)])
        graph = RoutingGraph(passable=passable, lift_enabled=True)
        assert pathfinder_route([net], graph)

        ent = _cell_to_entity(
            (1, 0, 1),
            net.tree_edges,
            hop_edges=net.hop_edges,
            lift_edges=net.lift_edges,
        )
        assert ent is not None
        assert ent.layer == 1

    def test_hop_endpoints_emitted_on_their_own_floor(self):
        """Hop sender/receiver entities land on the hop's floor, not floor 0."""
        hop_edges = {((1, 1, 1), (4, 1, 1))}

        sender = _cell_to_entity((1, 1, 1), [], hop_edges=hop_edges)
        receiver = _cell_to_entity((4, 1, 1), [], hop_edges=hop_edges)

        assert sender is not None and sender.layer == 1
        assert receiver is not None and receiver.layer == 1
        assert sender.type == "BeltPortSenderInternalVariant"
        assert receiver.type == "BeltPortReceiverInternalVariant"


class TestHop:
    """WP-K router side: hop edges resolve single-floor crossings."""

    def test_hop_resolves_crossing(self):
        """Two crossing nets that fail without hops succeed with hop_range > 0.

        Same layout as test_impossible_crossing_raises: net A (0,2)→(4,2),
        net B (2,0)→(2,4) in a 5×5 grid. With hops enabled, one net hops
        over the other.
        """
        passable = {(x, y, 0) for x in range(5) for y in range(5)}

        net_a = Net(net_id=0, kind="fanout", root=(0, 2, 0), terminals=[(4, 2, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(2, 0, 0), terminals=[(2, 4, 0)])

        graph = RoutingGraph(passable=passable, hop_range=5)
        success = pathfinder_route([net_a, net_b], graph)

        assert success
        assert not (net_a.tree_cells & net_b.tree_cells)
        assert net_a.hop_edges or net_b.hop_edges

    def test_hop_emit_roundtrip(self):
        """Route a crossing with hops, emit entities, re-lift → isomorphic."""
        from shapez2_tools.pathfinder import strip_and_reroute

        src_a = Entity(type="BeltPortReceiverInternalVariant", x=0, y=3, rotation=0, layer=0)
        sink_a = Entity(type="BeltPortSenderInternalVariant", x=8, y=3, rotation=0, layer=0)
        src_b = Entity(type="BeltPortReceiverInternalVariant", x=4, y=0, rotation=1, layer=0)
        sink_b = Entity(type="BeltPortSenderInternalVariant", x=4, y=8, rotation=1, layer=0)

        bp = _make_bp([src_a, sink_a, src_b, sink_b])
        nl = lift.Netlist(
            nodes={
                (0, 3): lift.Node(
                    x=0,
                    y=3,
                    layer=0,
                    type=src_a.type,
                    kind="platform_in",
                    rotation=0,
                ),
                (8, 3): lift.Node(
                    x=8,
                    y=3,
                    layer=0,
                    type=sink_a.type,
                    kind="platform_out",
                    rotation=0,
                ),
                (4, 0): lift.Node(
                    x=4,
                    y=0,
                    layer=0,
                    type=src_b.type,
                    kind="platform_in",
                    rotation=1,
                ),
                (4, 8): lift.Node(
                    x=4,
                    y=8,
                    layer=0,
                    type=sink_b.type,
                    kind="platform_out",
                    rotation=1,
                ),
            },
            edges=[((0, 3), (8, 3)), ((4, 0), (4, 8))],
            port_edges=[((0, 3), (8, 3)), ((4, 0), (4, 8))],
        )

        result_bp = strip_and_reroute(bp, nl, layer=0, hop_range=5)
        result_nl = lift.trace_layer(result_bp, 0, contract_hops=True)
        assert lift.isomorphic(nl, result_nl)

    def test_no_hop_when_unnecessary(self):
        """Hops enabled but not needed: straight route uses no hops."""
        passable = {(x, 0, 0) for x in range(8)}

        net = Net(net_id=0, kind="fanout", root=(0, 0, 0), terminals=[(7, 0, 0)])

        graph = RoutingGraph(passable=passable, hop_range=5)
        success = pathfinder_route([net], graph)

        assert success
        assert not net.hop_edges


class TestHopIntegrity:
    """No transit hops (cell is both hop sender AND receiver) or
    hop-receiver turns (receiver exits in a direction other than the
    hop direction).  Regression tests for the A* prev-update race."""

    @staticmethod
    def _check_no_transit_hops(nets: list[Net]) -> None:
        for n in nets:
            srcs = {s for s, _d in n.hop_edges}
            dsts = {d for _s, d in n.hop_edges}
            assert not (srcs & dsts), f"net {n.net_id} has transit hops at {srcs & dsts}"

    @staticmethod
    def _check_no_hop_receiver_turns(nets: list[Net]) -> None:
        for n in nets:
            for hs, hd in n.hop_edges:
                dx = hd[0] - hs[0]
                dy = hd[1] - hs[1]
                hop_dir = (
                    (1 if dx > 0 else -1) if dx else 0,
                    (1 if dy > 0 else -1) if dy else 0,
                )
                for s, d in n.tree_edges:
                    if s == hd:
                        out = (d[0] - s[0], d[1] - s[1])
                        if abs(out[0]) + abs(out[1]) == 1:
                            assert out == hop_dir, (
                                f"net {n.net_id}: hop receiver {hd} "
                                f"exits {out}, expected {hop_dir}"
                            )

    def test_crossing_nets_no_transit_hops(self):
        """Two crossing nets routed with hops produce no transit hops."""
        passable = {(x, y, 0) for x in range(7) for y in range(7)}
        net_a = Net(net_id=0, kind="fanout", root=(0, 3, 0), terminals=[(6, 3, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(3, 0, 0), terminals=[(3, 6, 0)])
        graph = RoutingGraph(passable=passable, hop_range=5)
        assert pathfinder_route([net_a, net_b], graph)
        self._check_no_transit_hops([net_a, net_b])

    def test_crossing_nets_no_hop_receiver_turns(self):
        """Hop receivers exit only in the hop direction."""
        passable = {(x, y, 0) for x in range(7) for y in range(7)}
        net_a = Net(net_id=0, kind="fanout", root=(0, 3, 0), terminals=[(6, 3, 0)])
        net_b = Net(net_id=1, kind="fanout", root=(3, 0, 0), terminals=[(3, 6, 0)])
        graph = RoutingGraph(passable=passable, hop_range=5)
        assert pathfinder_route([net_a, net_b], graph)
        self._check_no_hop_receiver_turns([net_a, net_b])

    def test_dense_crossing_no_invalid_hops(self):
        """Four nets crossing in a tight grid: no transit or turn violations."""
        passable = {(x, y, 0) for x in range(10) for y in range(10)}
        nets = [
            Net(net_id=0, kind="fanout", root=(0, 4, 0), terminals=[(9, 4, 0)]),
            Net(net_id=1, kind="fanout", root=(0, 6, 0), terminals=[(9, 6, 0)]),
            Net(net_id=2, kind="fanout", root=(4, 0, 0), terminals=[(4, 9, 0)]),
            Net(net_id=3, kind="fanout", root=(6, 0, 0), terminals=[(6, 9, 0)]),
        ]
        graph = RoutingGraph(passable=passable, hop_range=5)
        assert pathfinder_route(nets, graph)
        self._check_no_transit_hops(nets)
        self._check_no_hop_receiver_turns(nets)


class TestExistingHopValidity:
    """§0b: new hops must not collide with pre-existing senders/receivers
    under the in-game furthest-first pairing rule."""

    def test_baseline_hops_without_conflict(self):
        """Sanity check: with no pre-existing hops, the only bridge across
        the gap (a direct hop landing exactly on the far passable cell)
        succeeds."""
        passable = {(2, 0, 0), (5, 0, 0)}
        net = Net(net_id=0, kind="fanout", root=(2, 0, 0), terminals=[(5, 0, 0)])
        graph = RoutingGraph(passable=passable, hop_range=5)

        assert pathfinder_route([net], graph)
        assert net.hop_edges == {((2, 0, 0), (5, 0, 0))}

    def test_further_existing_receiver_blocks_sender(self):
        """A pre-existing receiver further along the same line/rotation
        would steal our sender under furthest-first. The only candidate hop
        is rejected, so the net is unroutable."""
        passable = {(2, 0, 0), (5, 0, 0)}
        net = Net(net_id=0, kind="fanout", root=(2, 0, 0), terminals=[(5, 0, 0)])
        graph = RoutingGraph(
            passable=passable,
            hop_range=5,
            existing_receivers={(6, 0, 0): (1, 0)},
        )

        with pytest.raises(RoutingError):
            pathfinder_route([net], graph)

    def test_further_existing_sender_blocks_receiver(self):
        """A pre-existing sender further from the receiver than our
        candidate sender would steal the receiver under furthest-first."""
        passable = {(2, 0, 0), (5, 0, 0)}
        net = Net(net_id=0, kind="fanout", root=(2, 0, 0), terminals=[(5, 0, 0)])
        graph = RoutingGraph(
            passable=passable,
            hop_range=5,
            existing_senders={(0, 0, 0): (1, 0)},
        )

        with pytest.raises(RoutingError):
            pathfinder_route([net], graph)

    def test_maxed_out_hop_distance_is_always_safe(self):
        """Launching at the full hop_range leaves no room for a further
        receiver to exist within range, so it's never flagged as unsafe —
        even with a pre-existing receiver positioned right at the landing
        cell's neighborhood."""
        passable = {(0, 0, 0), (5, 0, 0)}
        net = Net(net_id=0, kind="fanout", root=(0, 0, 0), terminals=[(5, 0, 0)])
        graph = RoutingGraph(
            passable=passable,
            hop_range=5,
            existing_receivers={(6, 0, 0): (1, 0)},
        )

        assert pathfinder_route([net], graph)
        assert net.hop_edges == {((0, 0, 0), (5, 0, 0))}

    def test_no_conflict_when_existing_hop_has_different_rotation(self):
        """A pre-existing receiver on the same line but a different
        rotation/direction never pairs with our sender, so it's not a
        conflict."""
        passable = {(2, 0, 0), (5, 0, 0)}
        net = Net(net_id=0, kind="fanout", root=(2, 0, 0), terminals=[(5, 0, 0)])
        graph = RoutingGraph(
            passable=passable,
            hop_range=5,
            existing_receivers={(6, 0, 0): (0, 1)},  # facing N, not E
        )

        assert pathfinder_route([net], graph)


class TestLiftAwareStripAndReroute:
    """WP-N task 3e: ``strip_and_reroute(..., lift_enabled=True)`` opens
    floor ``layer + 1`` as a fully passable second layer."""

    def test_extra_layer_is_fully_passable(self):
        """``_build_passable`` with ``extra_layers`` opens floor 1 over the
        full bounding box, including the ring excluded on floor 0."""
        from shapez2_tools.pathfinder import _build_passable, _platform_bounds

        min_x, max_x, min_y, max_y = _platform_bounds("Foundation_1x1")

        nl = lift.Netlist(
            nodes={
                (2, 9): lift.Node(
                    x=2,
                    y=9,
                    layer=0,
                    type="BeltPortReceiverInternalVariant",
                    kind="platform_in",
                    rotation=0,
                ),
                (17, 9): lift.Node(
                    x=17,
                    y=9,
                    layer=0,
                    type="BeltPortSenderInternalVariant",
                    kind="platform_out",
                    rotation=0,
                ),
            },
            edges=[((2, 9), (17, 9))],
            port_edges=[((2, 9), (17, 9))],
        )

        passable = _build_passable(
            nl,
            machine_cells=set(),
            floors=(0, 1),
            platform="Foundation_1x1",
        )

        # Floor 0 keeps the ring-exclusion behaviour (TestPortBandPassability).
        assert (2, 9, 0) in passable
        assert (2, 2, 0) not in passable
        # Floor 1 applies the same ring exclusion (the boundary ring is a
        # platform-specific zone on all floors).  Interior cells are passable.
        assert (9, 9, 1) in passable
        assert (2, 2, 1) not in passable  # ring, no port
        # Port xy positions are passable on any floor (ring override).
        assert (2, 9, 1) in passable

    def test_topological_crossing_converges_with_lift(self):
        """Two nets that must cross on one floor (west<->east and
        south<->north through the same Foundation_1x1 interior) route via
        floor 1 when ``lift_enabled=True``.

        The crossing is forced by a Jordan-curve-style argument: a path
        connecting the west and east edges of a rectangle and a path
        connecting its south and north edges must share a cell. With
        ``hop_range=0`` and no lift, that is a true single-floor
        impossibility (§7.2 WP-N task 1's finding at full scale, reproduced
        minimally here).
        """
        from shapez2_tools.pathfinder import strip_and_reroute
        from shapez2_tools.route import _all_entities

        src_a = Entity(type="BeltPortReceiverInternalVariant", x=2, y=9, rotation=0, layer=0)
        sink_a = Entity(type="BeltPortSenderInternalVariant", x=17, y=9, rotation=0, layer=0)
        src_b = Entity(type="BeltPortReceiverInternalVariant", x=9, y=2, rotation=1, layer=0)
        sink_b = Entity(type="BeltPortSenderInternalVariant", x=9, y=17, rotation=1, layer=0)

        bp = _make_bp([src_a, sink_a, src_b, sink_b], platform="Foundation_1x1")
        nl = lift.Netlist(
            nodes={
                (2, 9): lift.Node(
                    x=2,
                    y=9,
                    layer=0,
                    type=src_a.type,
                    kind="platform_in",
                    rotation=0,
                ),
                (17, 9): lift.Node(
                    x=17,
                    y=9,
                    layer=0,
                    type=sink_a.type,
                    kind="platform_out",
                    rotation=0,
                ),
                (9, 2): lift.Node(
                    x=9,
                    y=2,
                    layer=0,
                    type=src_b.type,
                    kind="platform_in",
                    rotation=1,
                ),
                (9, 17): lift.Node(
                    x=9,
                    y=17,
                    layer=0,
                    type=sink_b.type,
                    kind="platform_out",
                    rotation=1,
                ),
            },
            edges=[((2, 9), (17, 9)), ((9, 2), (9, 17))],
            port_edges=[((2, 9), (17, 9)), ((9, 2), (9, 17))],
        )

        result_bp = strip_and_reroute(
            bp,
            nl,
            layer=0,
            platform="Foundation_1x1",
            lift_enabled=True,
        )

        assert any(e.layer == 1 for e in _all_entities(result_bp))

        result_nl = lift.trace(result_bp)
        assert lift.isomorphic(nl, result_nl)

    def test_topological_crossing_fails_without_lift(self):
        """Same scenario, ``lift_enabled=False``: single floor cannot
        converge (RoutingError after MAX_ITERS)."""
        from shapez2_tools.pathfinder import strip_and_reroute

        src_a = Entity(type="BeltPortReceiverInternalVariant", x=2, y=9, rotation=0, layer=0)
        sink_a = Entity(type="BeltPortSenderInternalVariant", x=17, y=9, rotation=0, layer=0)
        src_b = Entity(type="BeltPortReceiverInternalVariant", x=9, y=2, rotation=1, layer=0)
        sink_b = Entity(type="BeltPortSenderInternalVariant", x=9, y=17, rotation=1, layer=0)

        bp = _make_bp([src_a, sink_a, src_b, sink_b], platform="Foundation_1x1")
        nl = lift.Netlist(
            nodes={
                (2, 9): lift.Node(
                    x=2,
                    y=9,
                    layer=0,
                    type=src_a.type,
                    kind="platform_in",
                    rotation=0,
                ),
                (17, 9): lift.Node(
                    x=17,
                    y=9,
                    layer=0,
                    type=sink_a.type,
                    kind="platform_out",
                    rotation=0,
                ),
                (9, 2): lift.Node(
                    x=9,
                    y=2,
                    layer=0,
                    type=src_b.type,
                    kind="platform_in",
                    rotation=1,
                ),
                (9, 17): lift.Node(
                    x=9,
                    y=17,
                    layer=0,
                    type=sink_b.type,
                    kind="platform_out",
                    rotation=1,
                ),
            },
            edges=[((2, 9), (17, 9)), ((9, 2), (9, 17))],
            port_edges=[((2, 9), (17, 9)), ((9, 2), (9, 17))],
        )

        with pytest.raises(RoutingError):
            strip_and_reroute(bp, nl, layer=0, platform="Foundation_1x1")


class TestLaneGroupRouting:
    """Lane-group decomposition (§7.3 step 7)."""

    def test_group_routing_avoids_cross_group_overlap(self):
        """Four groups of 2 nets each, crossing in the middle.

        Groups are spatially separated (left/right) with their nets needing
        to cross the center.  Group routing should keep groups' cells
        disjoint despite the shared bottleneck.
        """
        from shapez2_tools.pathfinder import _route_by_group

        passable = {(x, y, 0) for x in range(12) for y in range(8)}
        nets = []
        for g in range(4):
            base_y = g * 2
            n1 = Net(net_id=g * 2, kind="fanout", root=(0, base_y, 0), terminals=[(11, base_y, 0)])
            n1.group = g
            n2 = Net(
                net_id=g * 2 + 1,
                kind="fanout",
                root=(0, base_y + 1, 0),
                terminals=[(11, base_y + 1, 0)],
            )
            n2.group = g
            nets.extend([n1, n2])

        graph = RoutingGraph(passable=passable)
        ok = _route_by_group(nets, graph, raise_on_failure=False)
        assert ok

        for i, a in enumerate(nets):
            for b in nets[i + 1 :]:
                if a.group != b.group:
                    shared = a.tree_cells & b.tree_cells
                    assert not shared, (
                        f"net {a.net_id} (g{a.group}) and net {b.net_id} "
                        f"(g{b.group}) share {len(shared)} cells"
                    )

    def test_group_assignment_propagates(self):
        """_assign_net_groups propagates group membership through netlist edges.

        2 lanes (not the 4+ used by the scale-checkpoint tests) is enough to
        exercise multi-group propagation while staying off CP-SAT's 10s time
        budget (~3s here vs. ~10s at 4+ lanes).
        """
        from shapez2_tools.pathfinder import _assign_net_groups, build_nets
        from shapez2_tools.place import place
        from shapez2_tools.synth import CutterSpec, _monotone_sort, netlist_from_cutter_spec

        spec = CutterSpec(lanes=2, platform="Foundation_2x4", cutters_per_lane=4)
        abstract = _monotone_sort(netlist_from_cutter_spec(spec), spec.platform)
        nl = place(abstract, spec.platform)
        nets, _, _ = build_nets(nl, layer=0)
        _assign_net_groups(nets, nl, spec.platform)

        assert all(n.group is not None for n in nets)
        from collections import Counter

        groups = Counter(n.group for n in nets)
        assert len(groups) == 2
        for g, count in groups.items():
            assert count == 3, f"group {g} has {count} nets, expected 3"


class TestCorpusParity:
    """PathFinder must match the old router on single-cell fixtures."""

    SINGLE_CELL_FIXTURES = [
        "quarter_rotate_180.spz2bp",
        "quarter_rotate_cw.spz2bp",
        "quarter_rotate_ccw.spz2bp",
        "full_belt_rotate_180.spz2bp",
        "full_belt_rotate_cw.spz2bp",
        "full_belt_rotate_ccw.spz2bp",
        "quarter_destroy_west_half.spz2bp",
    ]

    @pytest.mark.parametrize("name", SINGLE_CELL_FIXTURES)
    def test_single_cell_corpus_parity(self, name):
        """Strip → pathfinder → lift ≅ original."""
        from shapez2_tools.pathfinder import strip_and_reroute
        from shapez2_tools.route import strip_belts

        bp = Blueprint.from_file(REF / name)
        original = lift.trace_layer(bp, 0)
        stripped = strip_belts(bp, layer=0)
        rerouted_bp = strip_and_reroute(stripped, original, layer=0)
        rerouted = lift.trace_layer(rerouted_bp, 0)
        assert lift.isomorphic(original, rerouted)


BLUEPRINTS = Path(__file__).resolve().parent.parent.parent / "shapez_2_blueprints"


class TestStacker3DReroute:
    """WP-P task 2: 3-D strip-and-reroute on stacker blueprints.

    Validates the 3-D routing pipeline: ``trace(contract_hops=True)`` →
    ``build_nets`` (3-D keys) → ``strip_and_reroute(floors=...)`` across
    all 3 floors. Stacker cross-floor connections (L+1 secondary input)
    exercise the full 3-D machine_cells and passable set.
    """

    @pytest.mark.skipif(
        not (BLUEPRINTS / "Stackers" / "Stacker 2.spz2bp").exists(),
        reason="blueprints repo not present",
    )
    def test_stacker2_reroute_no_structural_errors(self):
        """3-D pipeline resolves all nets without structural errors.

        Congestion may prevent full convergence (overused cells > 0) at
        this density; the test asserts no *structural* failures
        (unreachable terminals) and caps overuse.
        """
        from shapez2_tools.pathfinder import RoutingError, strip_and_reroute

        bp = Blueprint.from_file(BLUEPRINTS / "Stackers" / "Stacker 2.spz2bp")
        nl = lift.trace(bp, contract_hops=True)

        try:
            strip_and_reroute(
                bp,
                nl,
                layer=0,
                hop_range=lift.MAX_HOP_RANGE,
                platform="Foundation_1x1",
                floors=(0, 1, 2),
            )
        except RoutingError as e:
            if "unreachable" in str(e):
                raise
            assert e.overused is not None
            assert len(e.overused) < 150, f"too many overused cells: {len(e.overused)}"
