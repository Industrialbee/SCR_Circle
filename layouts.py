# layouts.py
from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

TAU = 2.0 * math.pi


class LayoutError(Exception):
    pass


@dataclass(frozen=True)
class Edge:
    u: str
    v: str
    operator: str


def load_station_pairs(path: str) -> List[Edge]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise LayoutError(f"Missing station_pairs file: {path}") from e
    except json.JSONDecodeError as e:
        raise LayoutError(f"Invalid JSON in station_pairs file: {path}") from e

    if not isinstance(data, list):
        raise LayoutError("station_pairs.json must be a list of objects")

    edges: List[Edge] = []
    seen: Set[Tuple[str, str, str]] = set()
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise LayoutError(f"station_pairs row {i} is not an object")
        op = row.get("Operator")
        a = row.get("FirstStation")
        b = row.get("SecondStation")
        if not (isinstance(op, str) and isinstance(a, str) and isinstance(b, str)):
            raise LayoutError(f"station_pairs row {i} must have string fields Operator/FirstStation/SecondStation")
        if a == b:
            continue
        u, v = (a, b) if a < b else (b, a)
        key = (u, v, op)
        if key in seen:
            continue
        seen.add(key)
        edges.append(Edge(u=u, v=v, operator=op))
    return edges


def load_operator_colours(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise LayoutError(f"Missing operators file: {path}") from e
    except json.JSONDecodeError as e:
        raise LayoutError(f"Invalid JSON in operators file: {path}") from e

    if not isinstance(data, list):
        raise LayoutError("operators.json must be a list of objects")

    colours: Dict[str, str] = {}
    for i, row in enumerate(data):
        if not isinstance(row, dict):
            raise LayoutError(f"operators row {i} is not an object")
        op = row.get("Operator")
        col = row.get("Colour")
        if not (isinstance(op, str) and isinstance(col, str)):
            raise LayoutError(f"operators row {i} must have string fields Operator/Colour")
        colours[op] = col
    return colours


def build_graph(edges: Sequence[Edge]) -> Tuple[Set[str], Dict[str, Set[str]], Dict[Tuple[str, str], List[str]]]:
    nodes: Set[str] = set()
    adj: Dict[str, Set[str]] = defaultdict(set)
    pair_ops: Dict[Tuple[str, str], List[str]] = defaultdict(list)  # (u,v)-> [operator,...] (unique, deterministic)

    for e in edges:
        nodes.add(e.u)
        nodes.add(e.v)
        adj[e.u].add(e.v)
        adj[e.v].add(e.u)

        key = (e.u, e.v) if e.u < e.v else (e.v, e.u)
        if e.operator not in pair_ops[key]:
            pair_ops[key].append(e.operator)

    # Ensure deterministic operator ordering per pair
    for k in list(pair_ops.keys()):
        pair_ops[k] = sorted(pair_ops[k])

    return nodes, adj, pair_ops


def choose_centre(nodes: Iterable[str], adj: Dict[str, Set[str]], centre: Optional[str] = None) -> str:
    nodes_sorted = sorted(nodes)
    if centre is not None:
        if centre not in nodes_sorted:
            raise LayoutError(f"Requested centre '{centre}' not in stations")
        return centre

    # Highest degree; tie-break alphabetically
    best = None
    best_deg = -1
    for n in nodes_sorted:
        deg = len(adj.get(n, set()))
        if deg > best_deg:
            best, best_deg = n, deg
    if best is None:
        raise LayoutError("No nodes found")
    return best


def bfs_distances(root: str, adj: Dict[str, Set[str]]) -> Dict[str, int]:
    dist: Dict[str, int] = {root: 0}
    q = deque([root])
    while q:
        u = q.popleft()
        for v in sorted(adj.get(u, set())):  # sorted => deterministic
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def assign_rings(nodes: Set[str], adj: Dict[str, Set[str]], centre: str) -> Dict[str, int]:
    """
    ring = distance from component root + 1, with disconnected components placed outside existing rings
    deterministically.
    """
    ring: Dict[str, int] = {}

    assigned: Set[str] = set()
    current_max = 0

    def place_component(component_root: str, base_offset: int) -> None:
        nonlocal current_max
        dist = bfs_distances(component_root, adj)
        for n, d in dist.items():
            if n in assigned:
                continue
            r = base_offset + d + 1
            ring[n] = r
            assigned.add(n)
            current_max = max(current_max, r)

    # First: centre component
    place_component(centre, base_offset=0)

    # Other components: pick smallest unassigned node as next component root
    while len(assigned) < len(nodes):
        remaining = sorted(nodes - assigned)
        root = remaining[0]
        # push it outside by at least 1 ring beyond current max
        place_component(root, base_offset=current_max)

    return ring


def circular_mean(angles: List[float]) -> float:
    if not angles:
        return 0.0
    sx = sum(math.cos(a) for a in angles)
    sy = sum(math.sin(a) for a in angles)
    if sx == 0 and sy == 0:
        return 0.0
    return math.atan2(sy, sx) % TAU


def assign_angles(
    nodes: Set[str],
    adj: Dict[str, Set[str]],
    ring: Dict[str, int],
    centre: str,
    gap_radians: float = 0.0,
) -> Dict[str, float]:
    """
    Deterministic ring-by-ring angle assignment:
    - inner rings fixed first
    - each ring sorted by preferred angle from already-placed inner neighbours
    - spread evenly around TAU, leaving optional 'gap_radians' empty space
    """
    rings: Dict[int, List[str]] = defaultdict(list)
    for n in nodes:
        rings[ring[n]].append(n)
    for r in rings:
        rings[r] = sorted(rings[r])

    max_ring = max(rings.keys()) if rings else 1
    theta: Dict[str, float] = {}

    # Place centre at 0 radians
    theta[centre] = 0.0

    # Place ring 1 nodes: if centre isn't ring 1, still spread them
    for r in range(1, max_ring + 1):
        ring_nodes = rings.get(r, [])
        if not ring_nodes:
            continue
        # If centre is in this ring, remove it (already placed)
        if centre in ring_nodes:
            ring_nodes = [n for n in ring_nodes if n != centre]

        if not ring_nodes:
            continue

        preferred: List[Tuple[float, str]] = []
        for n in ring_nodes:
            inner_angles = []
            for nb in adj.get(n, set()):
                if nb in theta and ring.get(nb, 10**9) < r:
                    inner_angles.append(theta[nb])
            pref = circular_mean(inner_angles) if inner_angles else (hash(n) % 360) * (TAU / 360.0)
            preferred.append((pref, n))

        preferred.sort(key=lambda t: (t[0], t[1]))

        span = max(1e-6, TAU - max(0.0, gap_radians))
        step = span / len(preferred)
        start = (gap_radians / 2.0) % TAU

        for i, (_, n) in enumerate(preferred):
            theta[n] = (start + i * step) % TAU

    return theta


def superellipse_point(t: float, r: float, n: float, xscale: float, yscale: float) -> Tuple[float, float]:
    """
    Parametric superellipse:
        x = r*xscale * sgn(cos t) * |cos t|^(2/n)
        y = r*yscale * sgn(sin t) * |sin t|^(2/n)
    n=2 => ellipse; n>2 => squircle/lozenge feel
    """
    ct = math.cos(t)
    st = math.sin(t)

    def sgn(x: float) -> float:
        return -1.0 if x < 0 else 1.0

    p = 2.0 / max(1e-6, n)
    x = r * xscale * sgn(ct) * (abs(ct) ** p)
    y = r * yscale * sgn(st) * (abs(st) ** p)
    return x, y


def compute_positions(
    nodes: Set[str],
    ring: Dict[str, int],
    theta: Dict[str, float],
    base_radius: float,
    ring_gap: float,
    n: float,
    xscale: float,
    yscale: float,
) -> Dict[str, Tuple[float, float]]:
    pos: Dict[str, Tuple[float, float]] = {}
    for node in sorted(nodes):
        rlevel = ring[node]
        radius = base_radius + (rlevel - 1) * ring_gap
        ang = theta.get(node, 0.0)
        pos[node] = superellipse_point(ang, radius, n, xscale, yscale)
    return pos


def build_layout(
    edges: Sequence[Edge],
    centre: Optional[str],
    base_radius: float,
    ring_gap: float,
    n: float,
    xscale: float,
    yscale: float,
    angle_gap_radians: float = 0.0,
) -> Tuple[str, Set[str], Dict[str, Set[str]], Dict[Tuple[str, str], List[str]], Dict[str, int], Dict[str, float], Dict[str, Tuple[float, float]]]:
    nodes, adj, pair_ops = build_graph(edges)
    centre_node = choose_centre(nodes, adj, centre=centre)
    ring = assign_rings(nodes, adj, centre_node)
    theta = assign_angles(nodes, adj, ring, centre_node, gap_radians=angle_gap_radians)
    pos = compute_positions(nodes, ring, theta, base_radius, ring_gap, n, xscale, yscale)
    return centre_node, nodes, adj, pair_ops, ring, theta, pos

