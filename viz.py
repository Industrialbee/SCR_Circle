# viz.py
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Circle

TAU = 2.0 * math.pi


class VizError(Exception):
    pass


def _angle_of(x: float, y: float) -> float:
    return math.atan2(y, x) % TAU


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _shortest_angular_delta(a: float, b: float) -> float:
    """Return delta to go from a to b taking shortest direction, in (-pi, pi]."""
    d = (b - a + math.pi) % TAU - math.pi
    return d


def _polyline_to_beziers(points: List[Tuple[float, float]], smooth: float = 0.25) -> Path:
    """
    Convert a polyline into a smooth cubic Bézier Path using a simple tangent-based scheme.
    Deterministic, no randomness.
    """
    if len(points) < 2:
        raise VizError("Need at least 2 points for a polyline")

    # Compute tangents
    tangents: List[Tuple[float, float]] = []
    for i in range(len(points)):
        if i == 0:
            x0, y0 = points[0]
            x1, y1 = points[1]
            tangents.append((x1 - x0, y1 - y0))
        elif i == len(points) - 1:
            x0, y0 = points[-2]
            x1, y1 = points[-1]
            tangents.append((x1 - x0, y1 - y0))
        else:
            x0, y0 = points[i - 1]
            x2, y2 = points[i + 1]
            tangents.append((x2 - x0, y2 - y0))

    verts: List[Tuple[float, float]] = [points[0]]
    codes: List[int] = [Path.MOVETO]

    for i in range(len(points) - 1):
        (x0, y0) = points[i]
        (x1, y1) = points[i + 1]
        (tx0, ty0) = tangents[i]
        (tx1, ty1) = tangents[i + 1]

        # Control points
        c1 = (x0 + smooth * tx0, y0 + smooth * ty0)
        c2 = (x1 - smooth * tx1, y1 - smooth * ty1)

        verts.extend([c1, c2, (x1, y1)])
        codes.extend([Path.CURVE4, Path.CURVE4, Path.CURVE4])

    return Path(verts, codes)


def _arc_route_polyline(
    a_xy: Tuple[float, float],
    b_xy: Tuple[float, float],
    ring_radius_mid: float,
    arc_samples: int = 18,
) -> List[Tuple[float, float]]:
    """
    Route: radial from A to mid radius, arc along mid radius, radial to B.
    Arc done in XY around origin. This gives an obvious "ring-following" feel.
    """
    ax, ay = a_xy
    bx, by = b_xy
    ta = _angle_of(ax, ay)
    tb = _angle_of(bx, by)

    # Project A and B onto the mid radius at their angles
    a_mid = (ring_radius_mid * math.cos(ta), ring_radius_mid * math.sin(ta))
    b_mid = (ring_radius_mid * math.cos(tb), ring_radius_mid * math.sin(tb))

    d = _shortest_angular_delta(ta, tb)

    pts: List[Tuple[float, float]] = []
    pts.append((ax, ay))
    pts.append(a_mid)

    for i in range(1, arc_samples):
        t = i / arc_samples
        ang = (ta + d * t) % TAU
        pts.append((ring_radius_mid * math.cos(ang), ring_radius_mid * math.sin(ang)))

    pts.append(b_mid)
    pts.append((bx, by))
    return pts


def _bezier_route(
    a_xy: Tuple[float, float],
    b_xy: Tuple[float, float],
    bias_radius: float,
    normal_offset: float = 0.0,
) -> Path:
    """
    Single cubic Bézier biased toward a mid radius.
    Ensures curvature by pulling control points away from chord.
    """
    ax, ay = a_xy
    bx, by = b_xy
    ta = _angle_of(ax, ay)
    tb = _angle_of(bx, by)

    d = _shortest_angular_delta(ta, tb)
    tm = (ta + 0.5 * d) % TAU

    # Midpoint target on a "track" radius
    mx = bias_radius * math.cos(tm)
    my = bias_radius * math.sin(tm)

    # Direction normal for separation
    nx = -math.sin(tm)
    ny = math.cos(tm)
    mx += normal_offset * nx
    my += normal_offset * ny

    # Controls: pull from endpoints toward the mid "track"
    c1 = (_lerp(ax, mx, 0.55), _lerp(ay, my, 0.55))
    c2 = (_lerp(bx, mx, 0.55), _lerp(by, my, 0.55))

    verts = [(ax, ay), c1, c2, (bx, by)]
    codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]
    return Path(verts, codes)


@dataclass(frozen=True)
class DrawStyle:
    node_radius: float = 0.8
    edge_width: float = 2.2
    ring_width: float = 0.8
    label_size: int = 9
    label_pad: float = 2.5
    edge_alpha: float = 0.95
    ring_alpha: float = 0.12


def draw_map(
    *,
    pos: Dict[str, Tuple[float, float]],
    ring_levels: Dict[str, int],
    operators_colour: Dict[str, str],
    pair_ops: Dict[Tuple[str, str], List[str]],  # (u,v)-> [op...]
    out_path: str,
    show_rings: bool,
    base_radius: float,
    ring_gap: float,
    shape_n: float,
    xscale: float,
    yscale: float,
    edge_style: str = "arc",
    suppress_labels_over: Optional[int] = None,
    figsize: Tuple[float, float] = (10, 10),
    style: DrawStyle = DrawStyle(),
) -> None:
    if edge_style not in {"arc", "bezier"}:
        raise VizError("--edge-style must be 'arc' or 'bezier'")

    # Validate operator colours
    missing = set()
    for _, ops in pair_ops.items():
        for op in ops:
            if op not in operators_colour:
                missing.add(op)
    if missing:
        raise VizError(f"Missing operator colours for: {', '.join(sorted(missing))}")

    # Determine extent
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    if not xs or not ys:
        raise VizError("No positions to draw")

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    # Optional faint ring guides (draw as circles; if ellipse/lozenge, still gives a "concentric" cue)
    if show_rings:
        max_ring = max(ring_levels.values()) if ring_levels else 1
        for r in range(1, max_ring + 1):
            rad = base_radius + (r - 1) * ring_gap
            circ = plt.Circle((0, 0), rad, fill=False, linewidth=style.ring_width, alpha=style.ring_alpha)
            ax.add_patch(circ)

    # Edge multiplicity offsets
    # For each unordered pair, if multiple operators, draw parallel curves with deterministic offsets.
    # Offsets are symmetric around zero.
    for (u, v), ops in sorted(pair_ops.items()):
        ax_u, ay_u = pos[u]
        ax_v, ay_v = pos[v]

        # Heuristic mid radius based on endpoints
        ru = math.hypot(ax_u, ay_u)
        rv = math.hypot(ax_v, ay_v)
        base_mid = max(ru, rv) + 0.25 * ring_gap

        m = len(ops)
        for i, op in enumerate(ops):
            # Offset index in [-k..k]
            offset_index = i - (m - 1) / 2.0
            # Separation tuned to be visible
            sep = 0.18 * ring_gap * offset_index

            color = operators_colour[op]

            if edge_style == "arc":
                mid = max(4.0, base_mid + sep)
                poly = _arc_route_polyline((ax_u, ay_u), (ax_v, ay_v), ring_radius_mid=mid, arc_samples=22)
                path = _polyline_to_beziers(poly, smooth=0.22)
            else:
                # normal offset gives visible parallel bezier curves
                path = _bezier_route((ax_u, ay_u), (ax_v, ay_v), bias_radius=base_mid, normal_offset=sep)

            patch = PathPatch(
                path,
                facecolor="none",
                edgecolor=color,
                linewidth=style.edge_width,
                alpha=style.edge_alpha,
                capstyle="round",
                joinstyle="round",
                zorder=1,
            )
            ax.add_patch(patch)

    # Nodes
    for node in sorted(pos.keys()):
        x, y = pos[node]
        circ = Circle((x, y), radius=style.node_radius, facecolor="white", edgecolor="black", linewidth=1.2, zorder=3)
        ax.add_patch(circ)

    # Labels (optional suppression for crowded maps)
    do_labels = True
    if suppress_labels_over is not None and len(pos) > suppress_labels_over:
        do_labels = False

    if do_labels:
        for node in sorted(pos.keys()):
            x, y = pos[node]
            ang = _angle_of(x, y)
            lx = x + style.label_pad * math.cos(ang)
            ly = y + style.label_pad * math.sin(ang)
            ha = "left" if math.cos(ang) >= 0 else "right"
            va = "bottom" if math.sin(ang) >= 0 else "top"
            ax.text(lx, ly, node, fontsize=style.label_size, ha=ha, va=va, zorder=4)

    # Expand limits with padding
    pad = ring_gap * 1.2 + 10
    xmin, xmax = min(xs) - pad, max(xs) + pad
    ymin, ymax = min(ys) - pad, max(ys) + pad
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)

    fig.savefig(out_path, dpi=200, bbox_inches="tight", transparent=False)
    plt.close(fig)

