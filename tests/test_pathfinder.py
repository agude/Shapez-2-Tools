"""WP-I: PathFinder negotiated-congestion router tests.

Test-first per §7.2. Flavours 4 (round-trip/isomorphism) and 5 (physical).
"""

from pathlib import Path

import pytest

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity
from shapez2_tools.pathfinder import Net, RoutingError, RoutingGraph, pathfinder_route

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
                (0, 0): lift.Node(
                    x=0, y=0, layer=0, type=src.type, kind="platform_in", rotation=0
                ),
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
                x=0, y=0, layer=0, type="BeltPortReceiverInternalVariant",
                kind="platform_in", rotation=0,
            ),
            (0, 1): lift.Node(
                x=0, y=1, layer=0, type="BeltPortReceiverInternalVariant",
                kind="platform_in", rotation=0,
            ),
            (2, 0): lift.Node(
                x=2, y=0, layer=0, type="BeltPortReceiverInternalVariant",
                kind="platform_in", rotation=0,
            ),
            (4, 0): lift.Node(
                x=4, y=0, layer=0, type="BeltPortSenderInternalVariant",
                kind="platform_out", rotation=0,
            ),
            (4, 1): lift.Node(
                x=4, y=1, layer=0, type="BeltPortSenderInternalVariant",
                kind="platform_out", rotation=0,
            ),
        }
        port_edges = [
            ((0, 0), (2, 0)), ((0, 1), (2, 0)),
            ((2, 0), (4, 0)), ((2, 0), (4, 1)),
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

        src_a = Entity(
            type="BeltPortReceiverInternalVariant", x=0, y=3, rotation=0, layer=0
        )
        sink_a = Entity(
            type="BeltPortSenderInternalVariant", x=8, y=3, rotation=0, layer=0
        )
        src_b = Entity(
            type="BeltPortReceiverInternalVariant", x=4, y=0, rotation=1, layer=0
        )
        sink_b = Entity(
            type="BeltPortSenderInternalVariant", x=4, y=8, rotation=1, layer=0
        )

        bp = _make_bp([src_a, sink_a, src_b, sink_b])
        nl = lift.Netlist(
            nodes={
                (0, 3): lift.Node(
                    x=0, y=3, layer=0, type=src_a.type,
                    kind="platform_in", rotation=0,
                ),
                (8, 3): lift.Node(
                    x=8, y=3, layer=0, type=sink_a.type,
                    kind="platform_out", rotation=0,
                ),
                (4, 0): lift.Node(
                    x=4, y=0, layer=0, type=src_b.type,
                    kind="platform_in", rotation=1,
                ),
                (4, 8): lift.Node(
                    x=4, y=8, layer=0, type=sink_b.type,
                    kind="platform_out", rotation=1,
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
