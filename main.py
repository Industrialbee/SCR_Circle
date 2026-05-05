# main.py
from __future__ import annotations

import argparse
import os
import sys

from layouts import (
    LayoutError,
    build_layout,
    load_operator_colours,
    load_station_pairs,
)
from viz import VizError, draw_map


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Concentric circuit-style tube map renderer (matplotlib).")

    p.add_argument("--pairs", required=True, help="Path to station_pairs.json")
    p.add_argument("--operators", required=True, help="Path to operators.json")
    p.add_argument("--out", required=True, help="Output path (PNG recommended)")

    p.add_argument("--centre", default=None, help="Optional centre station name (default: highest degree)")

    p.add_argument("--shape", choices=["circle", "ellipse", "lozenge"], default="circle",
                   help="Preset shape. You can also set --n --xscale --yscale explicitly.")
    p.add_argument("--n", type=float, default=None, help="Superellipse exponent (2=circle/ellipse, >2=lozenge)")
    p.add_argument("--xscale", type=float, default=None, help="X scale for ellipse/superellipse")
    p.add_argument("--yscale", type=float, default=None, help="Y scale for ellipse/superellipse")

    p.add_argument("--base-radius", type=float, default=18.0, help="Radius of ring 1")
    p.add_argument("--ring-gap", type=float, default=12.0, help="Gap between rings")

    p.add_argument("--show-rings", type=str, default="true", help="true|false to draw faint ring guides")
    p.add_argument("--edge-style", choices=["arc", "bezier"], default="arc", help="Edge routing style")

    p.add_argument("--suppress-labels-over", type=int, default=None,
                   help="If set, suppress labels when node count exceeds this value")

    return p.parse_args(argv)


def shape_params(shape: str, n: float | None, xscale: float | None, yscale: float | None) -> tuple[float, float, float]:
    # Presets
    if shape == "circle":
        n0, xs0, ys0 = 2.0, 1.0, 1.0
    elif shape == "ellipse":
        n0, xs0, ys0 = 2.0, 1.25, 0.90
    else:  # lozenge
        n0, xs0, ys0 = 4.2, 1.15, 0.95

    return (n if n is not None else n0,
            xscale if xscale is not None else xs0,
            yscale if yscale is not None else ys0)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    show_rings = args.show_rings.strip().lower() in {"1", "true", "yes", "y", "t"}

    n, xscale, yscale = shape_params(args.shape, args.n, args.xscale, args.yscale)

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    try:
        edges = load_station_pairs(args.pairs)
        op_col = load_operator_colours(args.operators)

        centre, nodes, adj, pair_ops, ring, theta, pos = build_layout(
            edges=edges,
            centre=args.centre,
            base_radius=args.base_radius,
            ring_gap=args.ring_gap,
            n=n,
            xscale=xscale,
            yscale=yscale,
            angle_gap_radians=0.0,
        )

        draw_map(
            pos=pos,
            ring_levels=ring,
            operators_colour=op_col,
            pair_ops=pair_ops,
            out_path=args.out,
            show_rings=show_rings,
            base_radius=args.base_radius,
            ring_gap=args.ring_gap,
            shape_n=n,
            xscale=xscale,
            yscale=yscale,
            edge_style=args.edge_style,
            suppress_labels_over=args.suppress_labels_over,
        )

        print(f"Centre: {centre}")
        print(f"Wrote: {args.out}")
        return 0

    except (LayoutError, VizError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

