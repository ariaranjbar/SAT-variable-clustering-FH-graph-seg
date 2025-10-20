#!/usr/bin/env python
"""Plot segmentation-result metrics as a family-coloured scatter plot."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from family_map_utils import families_for_csvs
from plot_styles import build_family_styles

DEFAULT_META = Path("benchmarks/sc2024/meta.csv")
DEFAULT_X = "vars"
DEFAULT_Y = "clauses"


def ensure_parent(path: Path) -> None:
    """Create output directories when saving figures."""
    path.parent.mkdir(parents=True, exist_ok=True)


def attach_families(frame: pd.DataFrame, meta_csv: Path) -> pd.Series:
    """Return the family label for each row using hash lookups."""
    if "file" not in frame.columns:
        raise ValueError("CSV must include a 'file' column for hash lookup")
    if not meta_csv.exists():
        print(f"Warning: meta file {meta_csv} not found; labelling families as 'unknown'.")
        return pd.Series(["unknown"] * len(frame))

    paths = [Path(str(name)) for name in frame["file"].astype(str)]
    fam_map = families_for_csvs(paths, meta_csv)
    return pd.Series([fam_map.get(path, "unknown") for path in paths])


def compute_marker_sizes(frame: pd.DataFrame, size_column: Optional[str]) -> pd.Series:
    """Scale marker sizes from a numeric column or return a constant size."""
    base = pd.Series(80.0, index=frame.index, dtype=float)
    if size_column is None:
        return base
    if size_column not in frame.columns:
        raise ValueError(f"Column '{size_column}' not found for marker sizing")

    values = pd.to_numeric(frame[size_column], errors="coerce")
    mask = values.replace([np.inf, -np.inf], np.nan).notna()
    if not mask.any():
        return base

    valid = values[mask]
    span = float(valid.max() - valid.min())
    if span <= 1e-12:
        base.loc[mask] = 160.0
        return base

    norm = (valid - float(valid.min())) / span
    base.loc[mask] = norm * 160.0 + 40.0
    return base


def filter_numeric(frame: pd.DataFrame, x_col: str, y_col: str) -> pd.DataFrame:
    """Keep rows where both x and y columns are finite numbers."""
    if x_col not in frame.columns or y_col not in frame.columns:
        missing = [col for col in (x_col, y_col) if col not in frame.columns]
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")

    subset = frame[[x_col, y_col]].apply(pd.to_numeric, errors="coerce")
    mask = np.isfinite(subset[x_col]) & np.isfinite(subset[y_col])
    return frame.loc[mask].copy()


def plot_scatter(
    frame: pd.DataFrame,
    x_col: str,
    y_col: str,
    size_column: Optional[str],
    meta_csv: Path,
    out_path: Path,
    title: Optional[str],
    legend_columns: int,
    x_log: bool,
    y_log: bool,
) -> None:
    """Render and save the scatter plot grouped by family."""
    filtered = filter_numeric(frame, x_col, y_col)
    if filtered.empty:
        raise ValueError("No finite data points remain after filtering x/y values")

    filtered = filtered.assign(family=attach_families(filtered, meta_csv).astype(str))

    counts = filtered["family"].value_counts()
    kept = counts[counts > 3].index
    filtered = filtered[filtered["family"].isin(kept)].copy()
    if filtered.empty:
        raise ValueError("No families with at least 4 instances available to plot")

    sizes = compute_marker_sizes(filtered, size_column)

    styles = build_family_styles(filtered["family"].astype(str).tolist())

    fig, ax = plt.subplots(figsize=(10, 7))
    for family, group in filtered.groupby("family"):
        family_name = str(family)
        style = styles.get(family_name)
        if style is None:
            # Fallback for unexpected family names
            style = build_family_styles([family_name])[family_name]
        ax.scatter(
            group[x_col],
            group[y_col],
            s=sizes.loc[group.index],
            color=style.color,
            marker=style.marker,
            edgecolors="black",
            linewidths=0.4,
            alpha=0.85,
            label=f"{family_name} (n={len(group)})",
        )

    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    if title:
        ax.set_title(title)

    if x_log:
        ax.set_xscale("log")
    if y_log:
        ax.set_yscale("log")

    ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5), ncol=legend_columns, frameon=True)
    ax.grid(True, which="both", linestyle=":", linewidth=0.5)
    fig.tight_layout()

    ensure_parent(out_path)
    fig.savefig(out_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)


def default_output(csv_path: Path, x_col: str, y_col: str) -> Path:
    stem = csv_path.stem or "segmentation_results"
    return csv_path.with_name(f"{stem}_{x_col}_{y_col}_scatter.png")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scatter plot of segmentation metrics coloured by family",
    )
    parser.add_argument("csv", type=Path, help="Path to segmentation_results.csv or similar")
    parser.add_argument("--meta", type=Path, default=DEFAULT_META, help="Meta CSV containing hash->family mapping")
    parser.add_argument("--x", dest="x_col", default=DEFAULT_X, help="Column to plot on the X axis")
    parser.add_argument("--y", dest="y_col", default=DEFAULT_Y, help="Column to plot on the Y axis")
    parser.add_argument("--size-column", dest="size_col", default=None, help="Optional numeric column for marker sizes")
    parser.add_argument("--out", type=Path, default=None, help="PNG file to write (defaults beside the input CSV)")
    parser.add_argument("--title", type=str, default=None, help="Optional plot title")
    parser.add_argument("--legend-columns", type=int, default=1, help="Number of columns for the legend")
    parser.add_argument("--x-log", action="store_true", help="Render the X axis on a log scale")
    parser.add_argument("--y-log", action="store_true", help="Render the Y axis on a log scale")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if not args.csv.exists():
        raise FileNotFoundError(f"CSV not found: {args.csv}")

    frame = pd.read_csv(args.csv)
    out_path = args.out or default_output(args.csv, args.x_col, args.y_col)

    plot_scatter(
        frame=frame,
        x_col=args.x_col,
        y_col=args.y_col,
        size_column=args.size_col,
        meta_csv=args.meta,
        out_path=out_path,
        title=args.title,
        legend_columns=args.legend_columns,
        x_log=args.x_log,
        y_log=args.y_log,
    )
    print(f"Wrote scatter plot to {out_path}")


if __name__ == "__main__":
    main()
