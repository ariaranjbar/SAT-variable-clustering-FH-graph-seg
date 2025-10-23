#!/usr/bin/env python
"""Plot segmentation-result metrics as a family-coloured scatter plot."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Optional, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.artist import Artist
import numpy as np
import pandas as pd

from family_map_utils import families_for_csvs
from plot_styles import build_family_styles

DEFAULT_META = Path("benchmarks/sc2024/meta.csv")
DEFAULT_X = "edges"
DEFAULT_Y = "vig_build_sec"


def ensure_parent(path: Path) -> None:
    """Create output directories when saving figures."""
    path.parent.mkdir(parents=True, exist_ok=True)


def legend_output_path(plot_path: Path) -> Path:
    """Return a companion path for saving a detached legend image."""
    suffix = plot_path.suffix or ".png"
    stem = plot_path.stem or "scatter"
    return plot_path.with_name(f"{stem}_legend{suffix}")


def save_legend_figure(
    handles: Sequence[Artist],
    labels: Sequence[str],
    out_path: Path,
    *,
    columns: int,
    title: Optional[str] = None,
    fontsize: float = 10.0,
) -> Optional[Path]:
    """Persist legend entries as a standalone figure."""
    if not handles or not labels:
        return None

    n_columns = max(1, columns)
    rows = math.ceil(len(labels) / n_columns)
    width = max(3.0, 2.4 * n_columns)
    height = max(1.0, 0.5 * rows + 0.6)
    ensure_parent(out_path)
    fig = plt.figure(figsize=(width, height))
    fig.legend(
        handles,
        labels,
        loc="center",
        frameon=False,
        ncol=n_columns,
        fontsize=fontsize,
        title=title,
        title_fontsize=fontsize,
    )
    fig.tight_layout()
    fig.savefig(out_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)
    return out_path


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
    x_limits: Optional[Tuple[float, float]],
    y_limits: Optional[Tuple[float, float]],
    fontsize: float,
) -> Optional[Path]:
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
    legend_handles = []
    legend_labels = []
    for family, group in filtered.groupby("family"):
        family_name = str(family)
        style = styles.get(family_name)
        if style is None:
            # Fallback for unexpected family names
            style = build_family_styles([family_name])[family_name]
        handle = ax.scatter(
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
        legend_handles.append(handle)
        legend_labels.append(f"{family_name} (n={len(group)})")

    ax.set_xlabel(x_col, fontsize=fontsize)
    ax.set_ylabel(y_col, fontsize=fontsize)
    if title:
        ax.set_title(title, fontsize=fontsize)

    ax.tick_params(labelsize=fontsize)

    if x_log:
        ax.set_xscale("log")
    if y_log:
        ax.set_yscale("log")

    if x_limits is not None:
        xmin, xmax = x_limits
        if not (math.isfinite(xmin) and math.isfinite(xmax) and xmin < xmax):
            raise ValueError("Invalid x-limits: expected finite numbers with min < max")
        if x_log and (xmin <= 0 or xmax <= 0):
            raise ValueError("Log-scaled X axis requires positive limits")
        ax.set_xlim(x_limits)

    if y_limits is not None:
        ymin, ymax = y_limits
        if not (math.isfinite(ymin) and math.isfinite(ymax) and ymin < ymax):
            raise ValueError("Invalid y-limits: expected finite numbers with min < max")
        if y_log and (ymin <= 0 or ymax <= 0):
            raise ValueError("Log-scaled Y axis requires positive limits")
        ax.set_ylim(y_limits)

    ax.grid(True, which="both", linestyle=":", linewidth=0.5)
    fig.tight_layout()

    ensure_parent(out_path)
    fig.savefig(out_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)
    if legend_handles:
        legend_path = legend_output_path(out_path)
        return save_legend_figure(
            legend_handles,
            legend_labels,
            legend_path,
            columns=legend_columns,
            title="family",
            fontsize=fontsize,
        )
    return None


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
    parser.add_argument(
        "--fontsize",
        type=float,
        default=10.0,
        help="Font size (points) for axis labels, ticks, and legends",
    )
    parser.add_argument(
        "--x-limits",
        type=float,
        nargs=2,
        metavar=("X_MIN", "X_MAX"),
        default=None,
        help="Explicit X axis limits (min max) for standardized plots",
    )
    parser.add_argument(
        "--y-limits",
        type=float,
        nargs=2,
        metavar=("Y_MIN", "Y_MAX"),
        default=None,
        help="Explicit Y axis limits (min max) for standardized plots",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    if not args.csv.exists():
        raise FileNotFoundError(f"CSV not found: {args.csv}")

    frame = pd.read_csv(args.csv)
    out_path = args.out or default_output(args.csv, args.x_col, args.y_col)

    legend_path = plot_scatter(
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
        x_limits=tuple(args.x_limits) if args.x_limits else None,
        y_limits=tuple(args.y_limits) if args.y_limits else None,
        fontsize=float(args.fontsize),
    )
    print(f"Wrote scatter plot to {out_path}")
    if legend_path:
        print(f"Wrote legend to {legend_path}")


if __name__ == "__main__":
    main()
