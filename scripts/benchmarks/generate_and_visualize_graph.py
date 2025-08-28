#!/usr/bin/env python
"""
Generate graph CSVs (segmentation and VIG) for a given CNF file, then visualize them.

Behavior:
  - If input ends with .xz, stream-decompress via `xz -dc` and pipe into binaries.
  - Writes graph CSVs to scripts/benchmarks/out/graphs/graph_output.{seg|vig}.(node|edges).csv
  - Renders PNGs next to them via visualize_graph.py.

Requirements:
  - Built binaries:
      build/algorithms/segmentation/segmentation
      build/algorithms/vig_info/vig_info
  - Tools: xz (for .xz inputs)
  - Python deps (for visualization): matplotlib, networkx

Usage:
  python scripts/benchmarks/generate_and_visualize_graph.py <path/to/file.cnf[.xz]>
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    # This file lives at scripts/benchmarks/; repo root is two levels up
    return Path(__file__).resolve().parents[2]


def run(cmd, *, stdin=None, cwd: Path | None = None) -> None:
    # Pretty print and run a command, raising on failure
    print(f"$ {cmd if isinstance(cmd, str) else ' '.join(map(shlex.quote, cmd))}")
    try:
        if isinstance(cmd, str):
            res = subprocess.run(cmd, shell=True, stdin=stdin, cwd=str(cwd) if cwd else None, check=True)
        else:
            res = subprocess.run(cmd, stdin=stdin, cwd=str(cwd) if cwd else None, check=True)
    finally:
        if stdin is not None and hasattr(stdin, "close"):
            try:
                stdin.close()  # close pipe to avoid broken pipe in producers
            except Exception:
                pass
    return None


def ensure_exists(path: Path, kind: str) -> None:
    if not path.exists():
        sys.stderr.write(f"Missing {kind}: {path}\n")
        sys.exit(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate segmentation & VIG graph CSVs and visualize them.")
    parser.add_argument("input", help="Path to CNF file (.cnf or .cnf.xz)")
    parser.add_argument("--layout", default="spring", choices=["spring", "kamada", "spectral", "planar", "random"], help="Layout for visualization")
    parser.add_argument("--max-nodes", type=int, default=2000, help="Visualization cap for nodes (0=all)")
    parser.add_argument("--max-edges", type=int, default=8000, help="Visualization cap for edges (0=all)")
    args = parser.parse_args()

    root = repo_root()
    in_path = Path(args.input).resolve()
    if not in_path.exists():
        sys.stderr.write(f"Input file not found: {in_path}\n")
        sys.exit(2)

    seg_bin = root / "build/algorithms/segmentation/segmentation"
    vig_bin = root / "build/algorithms/vig_info/vig_info"
    visualize_py = root / "scripts/benchmarks/visualize_graph.py"
    ensure_exists(seg_bin, "binary")
    ensure_exists(vig_bin, "binary")
    ensure_exists(visualize_py, "script")

    out_dir = root / "scripts/benchmarks/out/graphs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fixed basenames as requested
    seg_prefix = out_dir / "graph_output.seg"
    vig_prefix = out_dir / "graph_output.vig"

    # Build commands
    is_xz = in_path.suffix == ".xz"
    seg_cmd = [str(seg_bin), "-i", "-" if is_xz else str(in_path), "--graph-out", str(seg_prefix), "-t", "0", "--tau", "50", "--k", "300"]
    vig_cmd = [str(vig_bin), "-i", "-" if is_xz else str(in_path), "--graph-out", str(vig_prefix), "-t", "0", "--tau", "50"]

    # Execute graph generation
    if is_xz:
        # xz -dc <file> | <bin> -i - ...
        xz_proc = subprocess.Popen(["xz", "-dc", str(in_path)], stdout=subprocess.PIPE)
        try:
            run(seg_cmd, stdin=xz_proc.stdout)
        finally:
            xz_proc.wait()

        xz_proc2 = subprocess.Popen(["xz", "-dc", str(in_path)], stdout=subprocess.PIPE)
        try:
            run(vig_cmd, stdin=xz_proc2.stdout)
        finally:
            xz_proc2.wait()
    else:
        run(seg_cmd)
        run(vig_cmd)

    # Visualize both
    in_base = in_path.name
    seg_nodes = f"{seg_prefix}.node.csv"
    seg_edges = f"{seg_prefix}.edges.csv"
    vig_nodes = f"{vig_prefix}.node.csv"
    vig_edges = f"{vig_prefix}.edges.csv"
    seg_png = f"{seg_prefix}.png"
    vig_png = f"{vig_prefix}.png"

    # Validate CSVs exist before visualization (the tools should have produced them)
    for p in [seg_nodes, seg_edges, vig_nodes, vig_edges]:
        if not os.path.isfile(p):
            sys.stderr.write(f"Expected graph CSV not found: {p}\n")
            sys.exit(3)

    vis_base = [
        (seg_nodes, seg_edges, seg_png, f"segmentation: {in_base}"),
        (vig_nodes, vig_edges, vig_png, f"VIG: {in_base}"),
    ]

    for nodes, edges, out_img, title in vis_base:
        cmd = [sys.executable, str(visualize_py), "--nodes", nodes, "--edges", edges, "--out", out_img, "--title", title, "--layout", args.layout, "--max-nodes", str(args.max_nodes), "--max-edges", str(args.max_edges)]
        run(cmd)

    print("Done. Images:")
    print(f"  {seg_png}")
    print(f"  {vig_png}")


if __name__ == "__main__":
    main()
