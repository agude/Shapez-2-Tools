"""HTML/SVG visualization for blueprints.

Renders a blueprint layer as an interactive HTML page with inline SVG.
Machines and ports are filled rectangles; belts are drawn as lines from
input-edge midpoint through center to output-edge midpoint, so junctions
naturally show their T/X topology.
"""

from __future__ import annotations

from shapez2_tools import lift
from shapez2_tools.blueprint import Blueprint
from shapez2_tools.generator import Entity, all_entities

CELL_PX = 28
MARGIN_PX = 30  # room for axis labels

_COLORS = {
    "bg": "#111118",
    "grid": "#282838",
    "belt": "#88bbcc",
    "junction": "#99ddee",
    "machine_rotator": "#4488cc",
    "machine_cutter": "#cc8844",
    "machine_swapper": "#8844cc",
    "machine_trash": "#cc4444",
    "machine_other": "#778888",
    "port_in": "#44aa55",
    "port_out": "#bbaa33",
    "failed": "#dd3333",
    "label": "#667788",
    "port_arrow_in": "#55dd66",
    "port_arrow_out": "#dddd44",
}

W, E, N, S = (-1, 0), (1, 0), (0, 1), (0, -1)


def _entity_fill(e: Entity) -> str | None:
    """Fill color for non-belt entities; None for belts."""
    t = e.type
    if "PortReceiver" in t:
        return _COLORS["port_in"]
    if "PortSender" in t:
        return _COLORS["port_out"]
    k = lift.kind(t)
    if k == "machine":
        if "Rotator" in t:
            return _COLORS["machine_rotator"]
        if "Cutter" in t:
            return _COLORS["machine_cutter"]
        if "Swap" in t:
            return _COLORS["machine_swapper"]
        if "Trash" in t or "Destroy" in t:
            return _COLORS["machine_trash"]
        return _COLORS["machine_other"]
    return None


def _edge_midpoint(
    cell_px_x: float, cell_px_y: float, side: tuple[int, int]
) -> tuple[float, float]:
    """SVG coordinates of the midpoint of a cell edge.

    Game north (0,+1) maps to the SVG top edge because Y is flipped.
    """
    if side == N:
        return cell_px_x + CELL_PX / 2, cell_px_y
    if side == S:
        return cell_px_x + CELL_PX / 2, cell_px_y + CELL_PX
    if side == E:
        return cell_px_x + CELL_PX, cell_px_y + CELL_PX / 2
    if side == W:
        return cell_px_x, cell_px_y + CELL_PX / 2
    return cell_px_x + CELL_PX / 2, cell_px_y + CELL_PX / 2


def _short_type(t: str) -> str:
    """Readable short name for tooltips."""
    for suffix in ("InternalVariant", "Variant", "Internal"):
        t = t.replace(suffix, "")
    return t


def _is_junction(t: str) -> bool:
    return "Splitter" in t or "Merger" in t


def render_html(
    bp: Blueprint,
    layer: int = 0,
    failed_edges: list[tuple[tuple[int, int], tuple[int, int]]] | None = None,
    title: str = "",
) -> str:
    """Render one floor of a blueprint as a self-contained HTML page."""
    entities = all_entities(bp)
    layer_ents = [e for e in entities if e.layer == layer]
    if not layer_ents:
        return (
            "<html><body style='color:#ccc;background:#111'>No entities on this layer</body></html>"
        )

    # Bounding box (expand for machine footprints)
    min_x = min(e.x for e in layer_ents)
    max_x = max(e.x for e in layer_ents)
    min_y = min(e.y for e in layer_ents)
    max_y = max(e.y for e in layer_ents)
    for e in layer_ents:
        fp = lift._machine_footprint(e.type, e.rotation)
        for dx, dy in fp:
            min_x = min(min_x, e.x + dx)
            max_x = max(max_x, e.x + dx)
            min_y = min(min_y, e.y + dy)
            max_y = max(max_y, e.y + dy)
    min_x -= 1
    max_x += 1
    min_y -= 1
    max_y += 1

    cols = max_x - min_x + 1
    rows = max_y - min_y + 1
    svg_w = cols * CELL_PX + 2 * MARGIN_PX
    svg_h = rows * CELL_PX + 2 * MARGIN_PX

    def to_svg(gx: int, gy: int) -> tuple[float, float]:
        """Game coords → SVG pixel coords (top-left of cell)."""
        return (
            MARGIN_PX + (gx - min_x) * CELL_PX,
            MARGIN_PX + (max_y - gy) * CELL_PX,
        )

    parts: list[str] = []

    # --- grid lines ---
    for c in range(cols + 1):
        x = MARGIN_PX + c * CELL_PX
        parts.append(
            f'<line x1="{x}" y1="{MARGIN_PX}" '
            f'x2="{x}" y2="{MARGIN_PX + rows * CELL_PX}" '
            f'stroke="{_COLORS["grid"]}" stroke-width="0.5"/>'
        )
    for r in range(rows + 1):
        y = MARGIN_PX + r * CELL_PX
        parts.append(
            f'<line x1="{MARGIN_PX}" y1="{y}" '
            f'x2="{MARGIN_PX + cols * CELL_PX}" y2="{y}" '
            f'stroke="{_COLORS["grid"]}" stroke-width="0.5"/>'
        )

    # --- axis labels ---
    for c in range(cols):
        gx = min_x + c
        x = MARGIN_PX + c * CELL_PX + CELL_PX / 2
        parts.append(
            f'<text x="{x}" y="{MARGIN_PX - 6}" '
            f'text-anchor="middle" fill="{_COLORS["label"]}" font-size="9">{gx}</text>'
        )
        parts.append(
            f'<text x="{x}" y="{MARGIN_PX + rows * CELL_PX + 14}" '
            f'text-anchor="middle" fill="{_COLORS["label"]}" font-size="9">{gx}</text>'
        )
    for r in range(rows):
        gy = max_y - r
        y = MARGIN_PX + r * CELL_PX + CELL_PX / 2 + 3
        parts.append(
            f'<text x="{MARGIN_PX - 4}" y="{y}" '
            f'text-anchor="end" fill="{_COLORS["label"]}" font-size="9">{gy}</text>'
        )

    # --- entities ---
    belt_lines: list[str] = []

    for e in layer_ents:
        fill = _entity_fill(e)
        tip = f"{_short_type(e.type)} ({e.x},{e.y}) R={e.rotation}"

        if fill is not None:
            # Machine or port: filled rectangle(s)
            fp = lift._machine_footprint(e.type, e.rotation)
            for (dx, dy), (fins, fouts) in fp.items():
                gx, gy = e.x + dx, e.y + dy
                px, py = to_svg(gx, gy)
                is_ext = dx != 0 or dy != 0
                opacity = "0.35" if is_ext else "0.65"
                parts.append(
                    f'<rect x="{px + 1}" y="{py + 1}" '
                    f'width="{CELL_PX - 2}" height="{CELL_PX - 2}" '
                    f'fill="{fill}" opacity="{opacity}" rx="3">'
                    f"<title>{tip}</title></rect>"
                )
                # Port-direction arrows inside the cell
                cx = px + CELL_PX / 2
                cy = py + CELL_PX / 2
                for s in fins:
                    ex, ey = _edge_midpoint(px, py, s)
                    belt_lines.append(
                        f'<line x1="{ex}" y1="{ey}" x2="{cx}" y2="{cy}" '
                        f'stroke="{_COLORS["port_arrow_in"]}" '
                        f'stroke-width="1.5" opacity="0.5"/>'
                    )
                for s in fouts:
                    ex, ey = _edge_midpoint(px, py, s)
                    belt_lines.append(
                        f'<line x1="{cx}" y1="{cy}" x2="{ex}" y2="{ey}" '
                        f'stroke="{_COLORS["port_arrow_out"]}" '
                        f'stroke-width="1.5" opacity="0.5"/>'
                    )
        else:
            # Belt: draw lines from each input edge through center to each output edge
            result = lift.routing_inout(e.type, e.rotation)
            if not result:
                continue
            ins, outs = result
            px, py = to_svg(e.x, e.y)
            cx = px + CELL_PX / 2
            cy = py + CELL_PX / 2
            is_junc = _is_junction(e.type)
            color = _COLORS["junction"] if is_junc else _COLORS["belt"]
            width = "2.5" if is_junc else "2"

            for s in ins:
                ex, ey = _edge_midpoint(px, py, s)
                belt_lines.append(
                    f'<line x1="{ex}" y1="{ey}" x2="{cx}" y2="{cy}" '
                    f'stroke="{color}" stroke-width="{width}">'
                    f"<title>{tip}</title></line>"
                )
            for s in outs:
                ex, ey = _edge_midpoint(px, py, s)
                belt_lines.append(
                    f'<line x1="{cx}" y1="{cy}" x2="{ex}" y2="{ey}" '
                    f'stroke="{color}" stroke-width="{width}">'
                    f"<title>{tip}</title></line>"
                )
            # Small dot at center for junctions
            if is_junc:
                belt_lines.append(
                    f'<circle cx="{cx}" cy="{cy}" r="2.5" '
                    f'fill="{color}" opacity="0.8">'
                    f"<title>{tip}</title></circle>"
                )

    parts.extend(belt_lines)

    # --- failed edges overlay ---
    if failed_edges:
        for (sx, sy), (dx, dy) in failed_edges:
            spx, spy = to_svg(sx, sy)
            dpx, dpy = to_svg(dx, dy)
            parts.append(
                f'<line x1="{spx + CELL_PX / 2}" y1="{spy + CELL_PX / 2}" '
                f'x2="{dpx + CELL_PX / 2}" y2="{dpy + CELL_PX / 2}" '
                f'stroke="{_COLORS["failed"]}" stroke-width="2" '
                f'stroke-dasharray="5,3" opacity="0.85"/>'
            )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{svg_w}" height="{svg_h}">\n' + "\n".join(parts) + "\n</svg>"
    )

    page_title = title or "Blueprint"
    legend_items = [
        ("Input port", _COLORS["port_in"]),
        ("Output port", _COLORS["port_out"]),
        ("Rotator", _COLORS["machine_rotator"]),
        ("Cutter", _COLORS["machine_cutter"]),
        ("Swapper", _COLORS["machine_swapper"]),
        ("Trash", _COLORS["machine_trash"]),
        ("Belt", _COLORS["belt"]),
        ("Junction", _COLORS["junction"]),
    ]
    if failed_edges:
        legend_items.append(("Failed edge", _COLORS["failed"]))

    legend_html = " ".join(
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
        f'<span style="display:inline-block;width:12px;height:12px;background:{c};'
        f'border-radius:2px;opacity:0.8"></span>'
        f'<span style="color:#99aabb;font-size:12px">{label}</span></span>'
        for label, c in legend_items
    )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{page_title}</title>
<style>
  body {{
    margin: 0;
    background: {_COLORS["bg"]};
    font-family: system-ui, sans-serif;
    color: #ccddee;
  }}
  .container {{
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 20px;
    gap: 12px;
  }}
  h1 {{ font-size: 16px; font-weight: 500; margin: 0; color: #8899aa; }}
  .legend {{ display: flex; flex-wrap: wrap; justify-content: center; }}
  .svg-wrap {{
    overflow: auto;
    max-width: 95vw;
    max-height: 85vh;
    border: 1px solid {_COLORS["grid"]};
    border-radius: 4px;
  }}
</style>
</head>
<body>
<div class="container">
  <h1>{page_title} &mdash; layer {layer}</h1>
  <div class="legend">{legend_html}</div>
  <div class="svg-wrap">{svg}</div>
</div>
</body>
</html>"""
