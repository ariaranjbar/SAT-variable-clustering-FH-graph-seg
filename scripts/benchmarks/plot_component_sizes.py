#!/usr/bin/env python
"""Plot component-size coverage and weights grouped by dataset family."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy.typing import NDArray

from family_map_utils import families_for_csvs, extract_hash_from_filename
from plot_styles import FamilyStyle, LINESTYLES, build_family_styles


DEFAULT_IN_ROOT = "scripts/benchmarks/out/components"
DEFAULT_OUT_DIR = "scripts/benchmarks/out/component_size_plots"
DEFAULT_RESULTS_CSV = "scripts/benchmarks/out/segmentation_results.csv"
DEFAULT_FILTER_CONFIG = "scripts/benchmarks/configs/segmentation_results_filters.example.json"
ID_MAP_FILENAME = "combined_size_id_map.csv"

_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ID_BASE = len(_ID_ALPHABET)
_ID_WIDTH = 3

PathLike = Union[str, Path]
NumericFilterConfig = Dict[str, Dict[str, float]]
ResultsIndex = Dict[str, Dict[str, Any]]
IntArray = NDArray[np.int_]
FloatArray = NDArray[np.float64]


@dataclass
class ComponentSeries:
    """In-memory representation of a component CSV file."""

    label: str
    path: Path
    sizes: IntArray
    weights: Optional[FloatArray] = None
    family: str = "unknown"
    identifier: str = ""

    def component_count(self) -> int:
        return int(self.sizes.size)

    def has_weights(self) -> bool:
        if self.weights is None or self.weights.shape != self.sizes.shape:
            return False
        return bool(np.isfinite(self.weights).any())

    def coverage_curve(self) -> Tuple[IntArray, FloatArray]:
        if self.sizes.size == 0:
            return np.array([], dtype=np.int_), np.array([], dtype=np.float64)
        sorted_sizes = np.sort(self.sizes)[::-1]
        cumulative = np.cumsum(sorted_sizes, dtype=np.float64)
        total = float(sorted_sizes.sum())
        if total <= 0:
            return np.array([], dtype=np.int_), np.array([], dtype=np.float64)
        x = np.arange(1, sorted_sizes.size + 1, dtype=np.int_)
        y = (cumulative / total) * 100.0
        return x, y.astype(np.float64)

    def avg_weight_curve(self) -> Optional[Tuple[IntArray, FloatArray]]:
        if not self.has_weights() or self.weights is None:
            return None
        order = np.argsort(self.sizes)[::-1]
        sorted_weights = np.asarray(self.weights[order], dtype=np.float64)
        finite_mask = np.isfinite(sorted_weights)
        cumulative_weight = np.cumsum(np.where(finite_mask, sorted_weights, 0.0), dtype=np.float64)
        cumulative_count = np.cumsum(finite_mask.astype(np.int_))
        averages = np.divide(
            cumulative_weight,
            cumulative_count,
            out=np.full_like(cumulative_weight, np.nan, dtype=np.float64),
            where=cumulative_count > 0,
        )
        x = np.arange(1, sorted_weights.size + 1, dtype=np.int_)
        return x, averages.astype(np.float64)


def _base62_id(idx: int) -> str:
    """Return a stable three-character base62 identifier for legend labels."""
    max_ids = _ID_BASE ** _ID_WIDTH
    if idx < 0 or idx >= max_ids:
        raise ValueError(f"ID capacity exceeded for width={_ID_WIDTH} and base={_ID_BASE}")
    chars: List[str] = []
    value = idx
    for _ in range(_ID_WIDTH):
        chars.append(_ID_ALPHABET[value % _ID_BASE])
        value //= _ID_BASE
    while len(chars) < _ID_WIDTH:
        chars.append(_ID_ALPHABET[0])
    return "".join(reversed(chars))


def ensure_dir(directory: Path) -> None:
    """Create *directory* and parents if they are missing."""
    directory.mkdir(parents=True, exist_ok=True)


def find_component_csvs(root: Path) -> List[Path]:
    """Return every *_components.csv file found under *root*."""
    return [path for path in root.rglob("*_components.csv") if path.is_file()]


def parse_labels_from_path(path: Path, in_root: Optional[Path]) -> Tuple[str, Optional[str], Optional[str]]:
    """Build human-friendly label metadata from a CSV path."""
    stem = path.name
    display_name = stem
    if stem.endswith("_components.csv"):
        core = stem[: -len("_components.csv")]
        dash = core.find("-")
        display_name = core[dash + 1 :] if dash != -1 else core

    tau = None
    kval = None
    for segment in path.parts:
        if segment.startswith("tau_"):
            tau = segment.split("_", 1)[1]
        if segment.startswith("k_"):
            kval = segment.split("_", 1)[1]

    if in_root is not None:
        try:
            relative = path.relative_to(in_root)
            name = relative.name
            display_name = name[: -len("_components.csv")] if name.endswith("_components.csv") else relative.stem
        except ValueError:
            pass

    return display_name, tau, kval


def _load_sizes_and_weights(csv_path: Path) -> Tuple[IntArray, Optional[FloatArray]]:
    """Load component sizes and optional weights, filtering zero-sized components."""
    df = pd.read_csv(csv_path)
    if "size" not in df.columns:
        return np.array([], dtype=np.int_), None
    sizes_numeric = pd.to_numeric(df["size"], errors="coerce").fillna(0).astype(int)
    mask = sizes_numeric > 0
    sizes = np.asarray(sizes_numeric[mask], dtype=np.int_)

    weights: Optional[FloatArray] = None
    if "min_internal_weight" in df.columns:
        weights_series = pd.to_numeric(df["min_internal_weight"], errors="coerce")
        weights_masked = weights_series[mask].fillna(np.nan)
        weights = np.asarray(weights_masked, dtype=np.float64)
    return sizes, weights


def _load_filter_config(path: Optional[Path]) -> Optional[NumericFilterConfig]:
    """Parse optional JSON filter thresholds for segmentation result pruning."""
    if path is None or not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        try:
            raw = json.load(handle)
        except json.JSONDecodeError:
            print(f"Warning: filter config {path} is not valid JSON; ignoring.")
            return None
    cfg: NumericFilterConfig = {"min": {}, "max": {}}
    for key in ("min", "max"):
        section = raw.get(key, {}) or {}
        cfg[key] = {str(name): float(value) for name, value in section.items()}
    return cfg


def _load_results_index(results_csv: Path) -> ResultsIndex:
    """Return segmentation results keyed by hash extracted from their file field."""
    if not results_csv.exists():
        raise FileNotFoundError(f"Results CSV not found: {results_csv}")
    df = pd.read_csv(results_csv)
    if "file" not in df.columns:
        raise ValueError("segmentation_results.csv must contain a 'file' column")
    index: ResultsIndex = {}
    for _, row in df.iterrows():
        hash_id = extract_hash_from_filename(str(row["file"]))
        if hash_id:
            index[hash_id] = {column: row[column] for column in df.columns}
    return index


def _row_value(row: Dict[str, Any], key: str) -> Optional[float]:
    """Best-effort conversion of a results row field into a float for comparisons."""
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        try:
            numeric = pd.to_numeric([value], errors="coerce")
        except Exception:
            return None
        result = float(numeric[0])
        if np.isnan(result):
            return None
        return result


def _passes_filters(row: Dict[str, Any], flt: NumericFilterConfig) -> Tuple[bool, Optional[str]]:
    """Return (True, None) if *row* satisfies thresholds; otherwise details of the failure."""
    for key, threshold in flt.get("min", {}).items():
        value = _row_value(row, key)
        if value is None:
            return False, f"missing value for '{key}' (required min {threshold})"
        if value < threshold:
            return False, f"min filter '{key}' failed: {value} < {threshold}"
    for key, threshold in flt.get("max", {}).items():
        value = _row_value(row, key)
        if value is None:
            return False, f"missing value for '{key}' (required max {threshold})"
        if value > threshold:
            return False, f"max filter '{key}' failed: {value} > {threshold}"
    return True, None


def _slugify(text: str) -> str:
    """Generate a filesystem-safe slug from *text* for PNG filenames."""
    safe = [ch if ch.isalnum() or ch in {"-", "."} else "_" for ch in text]
    slug = "".join(safe)
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")
    return slug or "family"


def _make_label(csv_path: Path, in_root: Optional[Path]) -> str:
    """Build the display label for a component CSV, including tau/k metadata."""
    name, tau, kval = parse_labels_from_path(csv_path, in_root)
    extras: List[str] = []
    if tau is not None:
        extras.append(f"tau={tau}")
    if kval is not None:
        extras.append(f"k={kval}")
    suffix = f" ({', '.join(extras)})" if extras else ""
    return f"{name}{suffix}"


def resolve_input_paths(args: argparse.Namespace) -> Tuple[List[Path], Optional[Path]]:
    """Resolve user-supplied inputs into concrete CSV paths and optional root."""
    if args.files:
        return [Path(p) for p in args.files], None
    root = Path(args.root)
    return find_component_csvs(root), root


def load_component_series(
    csv_paths: Sequence[Path],
    in_root: Optional[Path],
    filter_cfg: Optional[NumericFilterConfig],
    results_index: Optional[ResultsIndex],
)  -> List[ComponentSeries]:
    """Materialize ComponentSeries objects after applying size and results filters."""
    series: List[ComponentSeries] = []
    for csv_path in csv_paths:
        try:
            sizes, weights = _load_sizes_and_weights(csv_path)
        except Exception as exc:
            print(f"Failed to load {csv_path}: {exc}")
            continue

        if sizes.size <= 2:
            print(f"Skipping {csv_path} (only {sizes.size} components)")
            continue

        if filter_cfg and results_index:
            # Hash-based lookup matches segmentation results to component exports.
            hash_id = extract_hash_from_filename(csv_path.name)
            row = results_index.get(hash_id)
            if not row:
                print(f"Skipping {csv_path} (no results row for hash {hash_id})")
                continue
            passes_filters, reason = _passes_filters(row, filter_cfg)
            if not passes_filters:
                detail = reason or "failed filter thresholds"
                print(f"Skipping {csv_path} ({detail})")
                continue

        label = _make_label(csv_path, in_root)
        weights_array = weights if weights is not None and np.isfinite(weights).any() else None
        series.append(ComponentSeries(label=label, path=csv_path, sizes=sizes, weights=weights_array))
    return series


def assign_identifiers(series: List[ComponentSeries]) -> None:
    """Assign stable legend identifiers to each ComponentSeries instance."""
    for idx, record in enumerate(sorted(series, key=lambda item: item.label)):
        setattr(record, "identifier", _base62_id(idx))


def update_families(series: List[ComponentSeries], meta_path: Path) -> None:
    """Attach family metadata to each series using benchmarks/meta.csv."""
    if not series:
        return
    if meta_path.exists():
        try:
            families = families_for_csvs([record.path for record in series], meta_path)
        except Exception as exc:
            print(f"Warning: failed to derive families from meta {meta_path}: {exc}")
            families = {record.path: "unknown" for record in series}
    else:
        print(f"Warning: meta file {meta_path} not found; assigning 'unknown' family.")
        families = {record.path: "unknown" for record in series}

    for record in series:
        family = families.get(record.path, "unknown")
        setattr(record, "family", family if isinstance(family, str) and family.strip() else "unknown")


def write_id_map(out_dir: Path, series: Sequence[ComponentSeries], in_root: Optional[Path]) -> Path:
    """Persist a CSV translating compact IDs to source metadata for traceability."""
    rows: List[Dict[str, Any]] = []
    for record in sorted(series, key=lambda item: item.identifier):
        path_repr = _resolve_relative(record.path, in_root)
        rows.append(
            {
                "id": record.identifier,
                "label": record.label,
                "file": path_repr,
                "family": record.family,
                "n_sizes": record.component_count(),
            }
        )
    df = pd.DataFrame(rows, columns=["id", "label", "file", "family", "n_sizes"])
    out_path = out_dir / ID_MAP_FILENAME
    df.to_csv(out_path, index=False)
    return out_path


def _resolve_relative(path: Path, root: Optional[Path]) -> str:
    """Return path relative to *root* when possible for cleaner CSV output."""
    if root is not None:
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    return str(path)


def compute_valid_families(series: Sequence[ComponentSeries], excluded: Iterable[str]) -> Tuple[Dict[str, int], List[str]]:
    """Derive family membership counts, honoring minimum thresholds and exclusions."""
    counts = Counter(record.family for record in series)
    valid = {family for family, count in counts.items() if count >= 3}
    excluded_set = set(excluded)
    if excluded_set:
        print(f"\nExcluding families: {', '.join(sorted(excluded_set))}")
        valid -= excluded_set
    return dict(counts), sorted(valid)


def print_family_listing(series: Sequence[ComponentSeries], valid_families: Iterable[str]) -> None:
    """Emit a console summary mapping families to their component files."""
    valid_set = set(valid_families)
    print("\n" + "=" * 60)
    print("Families and their files (only families with >= 3 instances):")
    print("=" * 60)
    family_to_files: Dict[str, List[str]] = {}
    for record in series:
        if record.family not in valid_set:
            continue
        family_to_files.setdefault(record.family, []).append(record.path.name)
    for family in sorted(family_to_files):
        files = sorted(family_to_files[family])
        print(f"\n{family} ({len(files)} instances):")
        for name in files:
            print(f"  {name}")
    print("=" * 60 + "\n")


def _save_legend_image(handles: Sequence[Any], labels: Sequence[str], out_path: Path, *, title: str, fontsize: float) -> None:
    """Render a standalone legend image using *handles* and *labels*."""
    if not handles or not labels:
        return
    legend_height = max(1, len(labels))
    fig = plt.figure(figsize=(3.0, 0.35 * legend_height + 0.6))
    fig.legend(
        handles,
        labels,
        loc="center",
        frameon=False,
        ncol=1,
        title=title,
        fontsize=fontsize,
        title_fontsize=fontsize,
    )
    fig.tight_layout()
    fig.savefig(out_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)


def _style_sizes(fontsize: float, *, base_line: float, base_marker: float) -> Tuple[float, float]:
    """Scale line width and marker size relative to the reference font size (7pt)."""
    scale = max(fontsize / 10.0, 0.1)
    return base_line * scale, base_marker * scale


def plot_combined_coverage(
    series: Sequence[ComponentSeries],
    valid_families: Iterable[str],
    styles: Dict[str, FamilyStyle],
    out_dir: Path,
    title_prefix: str,
    total_files: int,
    fontsize: float,
) -> None:
    """Overlay coverage curves for every eligible file grouped by family."""
    valid_set = set(valid_families)
    path = out_dir / "combined_topn_coverage.png"
    fig, ax = plt.subplots(figsize=(10, 7))
    fam_handles: Dict[str, Any] = {}
    any_data = False
    line_width, marker_size = _style_sizes(fontsize, base_line=1.5, base_marker=3.0)
    for record in series:
        if record.family not in valid_set:
            continue
        x, y = record.coverage_curve()
        if x.size == 0:
            continue
        style = styles.get(record.family)
        if style is None:
            continue
        any_data = True
        line, = ax.plot(
            x,
            y,
            linewidth=line_width,
            color=style.color,
            linestyle=style.linestyle,
            alpha=0.9,
            marker=style.marker,
            markersize=marker_size,
            markevery=1,
        )
        fam_handles.setdefault(record.family, line)

    if not any_data:
        plt.close(fig)
        return

    ax.set_xscale("log")
    ax.set_xlabel("n (log)", fontsize=fontsize)
    ax.set_ylabel("percent covered by top-n components (%)", fontsize=fontsize)
    ax.tick_params(labelsize=fontsize)
    ax.set_ylim(bottom=0, top=100)
    ax.set_title(f"{title_prefix} — coverage by top-n components (N={total_files} files)", fontsize=fontsize)
    labels = sorted(fam_handles)
    handles = [fam_handles[label] for label in labels]
    fig.tight_layout()
    legend_path = path.with_name(f"{path.stem}_legend.png")
    _save_legend_image(handles, labels, legend_path, title="family", fontsize=fontsize)
    fig.savefig(path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_combined_avg_weights(
    series: Sequence[ComponentSeries],
    valid_families: Iterable[str],
    styles: Dict[str, FamilyStyle],
    out_dir: Path,
    title_prefix: str,
    total_files: int,
    fontsize: float,
) -> None:
    """Plot per-family averages of minimum internal weights across components."""
    valid_set = set(valid_families)
    path = out_dir / "combined_topn_avg_min_internal_weight.png"
    fig, ax = plt.subplots(figsize=(10, 7))
    fam_handles: Dict[str, Any] = {}
    any_data = False
    y_min = np.inf
    y_max = 0.0
    line_width, marker_size = _style_sizes(fontsize, base_line=1.5, base_marker=3.0)

    for record in series:
        if record.family not in valid_set:
            continue
        curve = record.avg_weight_curve()
        if curve is None:
            continue
        x, y = curve
        if x.size == 0:
            continue
        style = styles.get(record.family)
        if style is None:
            continue
        any_data = True
        # Track extrema so log-scale limits stay anchored to observed values.
        finite = y[np.isfinite(y) & (y > 0)]
        if finite.size > 0:
            y_min = min(y_min, float(np.min(finite)))
            y_max = max(y_max, float(np.max(finite)))
        line, = ax.plot(
            x,
            y,
            linewidth=line_width,
            color=style.color,
            linestyle=style.linestyle,
            alpha=0.9,
            marker=style.marker,
            markersize=marker_size,
            markevery=1,
        )
        fam_handles.setdefault(record.family, line)

    if not any_data:
        plt.close(fig)
        return

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("n (log)", fontsize=fontsize)
    ax.set_ylabel("average min_internal_weight of top-n components (log)", fontsize=fontsize)
    ax.tick_params(labelsize=fontsize)
    if np.isfinite(y_min) and y_max > 0:
        bottom = y_min / 1.25 if y_min > 0 else y_min
        top = y_max * 1.1 if y_max > 0 else y_max
        if bottom <= 0:
            bottom = y_min
        if top <= bottom:
            top = bottom * 1.1
        ax.set_ylim(bottom=bottom, top=top)
    ax.set_title(
        f"{title_prefix} — avg min_internal_weight by top-n components (N={total_files} files)",
        fontsize=fontsize,
    )
    labels = sorted(fam_handles)
    handles = [fam_handles[label] for label in labels]
    fig.tight_layout()
    legend_path = path.with_name(f"{path.stem}_legend.png")
    _save_legend_image(handles, labels, legend_path, title="family", fontsize=fontsize)
    fig.savefig(path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_family_curves(
    series: Sequence[ComponentSeries],
    family: str,
    style: FamilyStyle,
    out_dir: Path,
    title_prefix: str,
    fontsize: float,
) -> None:
    """Write per-family coverage and weight plots with legend keyed by file ID."""
    family_series = [record for record in series if record.family == family]
    if not family_series:
        return

    coverage_path = out_dir / f"topn_coverage_{_slugify(family)}.png"
    fig_cov, ax_cov = plt.subplots(figsize=(10, 7))
    any_coverage = False
    legend_handles_cov: List[Any] = []
    line_width_cov, marker_size_cov = _style_sizes(fontsize, base_line=1.3, base_marker=3.0)
    for idx, record in enumerate(sorted(family_series, key=lambda item: item.identifier)):
        x, y = record.coverage_curve()
        if x.size == 0:
            continue
        any_coverage = True
        # Rotate per-trace line styles to keep densely plotted families legible.
        linestyle = LINESTYLES[idx % len(LINESTYLES)]
        line, = ax_cov.plot(
            x,
            y,
            linewidth=line_width_cov,
            color=style.color,
            linestyle=linestyle,
            alpha=0.9,
            marker=style.marker,
            markersize=marker_size_cov,
            markevery=1,
            label=record.identifier,
        )
        legend_handles_cov.append(line)
    if any_coverage:
        ax_cov.set_xscale("log")
        ax_cov.set_xlabel("n (log)", fontsize=fontsize)
        ax_cov.set_ylabel("percent covered by top-n components (%)", fontsize=fontsize)
        ax_cov.tick_params(labelsize=fontsize)
        ax_cov.set_ylim(bottom=0, top=100)
        ax_cov.set_title(f"{title_prefix} — {family} (N={len(family_series)} files)", fontsize=fontsize)
        legend_labels_cov = [handle.get_label() for handle in legend_handles_cov]
        legend_path_cov = coverage_path.with_name(f"{coverage_path.stem}_legend.png")
        _save_legend_image(legend_handles_cov, legend_labels_cov, legend_path_cov, title="file id", fontsize=fontsize)
        fig_cov.tight_layout()
        fig_cov.savefig(coverage_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig_cov)

    avg_path = out_dir / f"topn_avg_min_internal_weight_{_slugify(family)}.png"
    fig_avg, ax_avg = plt.subplots(figsize=(10, 7))
    any_avg = False
    y_min = np.inf
    y_max = 0.0
    plotted = 0
    legend_handles_avg: List[Any] = []
    line_width_avg, marker_size_avg = _style_sizes(fontsize, base_line=1.3, base_marker=3.0)
    for idx, record in enumerate(sorted(family_series, key=lambda item: item.identifier)):
        curve = record.avg_weight_curve()
        if curve is None:
            continue
        x, y = curve
        if x.size == 0:
            continue
        any_avg = True
        plotted += 1
        # Track extrema so the family-specific log-scale remains informative.
        finite = y[np.isfinite(y) & (y > 0)]
        if finite.size > 0:
            y_min = min(y_min, float(np.min(finite)))
            y_max = max(y_max, float(np.max(finite)))
        # Rotate per-trace line styles to keep densely plotted families legible.
        linestyle = LINESTYLES[idx % len(LINESTYLES)]
        line, = ax_avg.plot(
            x,
            y,
            linewidth=line_width_avg,
            color=style.color,
            linestyle=linestyle,
            alpha=0.9,
            marker=style.marker,
            markersize=marker_size_avg,
            markevery=1,
            label=record.identifier,
        )
        legend_handles_avg.append(line)
    if any_avg:
        ax_avg.set_xscale("log")
        ax_avg.set_yscale("log")
        ax_avg.set_xlabel("n (log)", fontsize=fontsize)
        ax_avg.set_ylabel("average min_internal_weight of top-n components (log)", fontsize=fontsize)
        ax_avg.tick_params(labelsize=fontsize)
        if np.isfinite(y_min) and y_max > 0:
            bottom = y_min / 1.25 if y_min > 0 else y_min
            top = y_max * 1.1 if y_max > 0 else y_max
            if bottom <= 0:
                bottom = y_min
            if top <= bottom:
                top = bottom * 1.1
            ax_avg.set_ylim(bottom=bottom, top=top)
        ax_avg.set_title(
            f"{title_prefix} — {family} avg min_internal_weight (N={plotted} files)",
            fontsize=fontsize,
        )
        legend_labels_avg = [handle.get_label() for handle in legend_handles_avg]
        legend_path_avg = avg_path.with_name(f"{avg_path.stem}_legend.png")
        _save_legend_image(legend_handles_avg, legend_labels_avg, legend_path_avg, title="file id", fontsize=fontsize)
        fig_avg.tight_layout()
        fig_avg.savefig(avg_path.as_posix(), dpi=300, bbox_inches="tight")
    plt.close(fig_avg)


def main(argv: Optional[Sequence[str]] = None) -> None:
    """Script entry point handling argument parsing and plotting pipeline."""
    parser = argparse.ArgumentParser(
        description="Plot combined component-size distributions from *_components.csv files.")
    parser.add_argument("--root", type=Path, default=Path(DEFAULT_IN_ROOT), help="Root directory to scan for *_components.csv (recursive)")
    parser.add_argument("--files", type=Path, nargs="*", default=None, help="Specific *_components.csv files to process (overrides --root if given)")
    parser.add_argument("--outdir", type=Path, default=Path(DEFAULT_OUT_DIR), help="Directory to write combined plots")
    parser.add_argument("--title", type=str, default=None, help="Optional plot title prefix")
    parser.add_argument("--fontsize", type=float, default=7.0, help="Font size (points) for labels, ticks, and legends")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for deterministic family style assignment (color/marker/linestyle)")
    parser.add_argument("--meta", type=Path, default=Path("benchmarks/sc2024/meta.csv"), help="Path to benchmarks meta.csv with hash,family columns")
    parser.add_argument("--results-csv", type=Path, default=Path(DEFAULT_RESULTS_CSV), help="Path to segmentation_results.csv for additional filtering")
    parser.add_argument("--filter-config", type=Path, default=Path(DEFAULT_FILTER_CONFIG), help="JSON file with numeric min/max thresholds against segmentation_results.csv")
    parser.add_argument("--exclude-families", type=str, nargs="*", default=None, help="List of family names to exclude from plots")
    args = parser.parse_args(args=argv)

    ensure_dir(args.outdir)

    csv_paths, in_root = resolve_input_paths(args)
    if not csv_paths:
        print("No *_components.csv files found.")
        return

    filter_cfg = _load_filter_config(args.filter_config)
    results_index: Optional[ResultsIndex] = None
    if filter_cfg:
        try:
            results_index = _load_results_index(args.results_csv)
        except Exception as exc:
            print(f"Failed to load results CSV for filtering: {exc}")
            results_index = None

    series = load_component_series(csv_paths, in_root, filter_cfg, results_index)
    if not series:
        print("No valid component sizes to plot.")
        return

    assign_identifiers(series)
    update_families(series, args.meta)
    styles = build_family_styles((record.family for record in series), seed=args.seed)
    id_map_path = write_id_map(args.outdir, series, in_root)

    counts, valid_families = compute_valid_families(series, args.exclude_families or [])
    if not valid_families:
        print("No families satisfied the minimum count requirement.")
        print(f"Legend ID map: {id_map_path}")
        return

    print_family_listing(series, valid_families)

    prefix = args.title or "component size distribution"
    total_files = len(series)

    plot_combined_coverage(series, valid_families, styles, args.outdir, prefix, total_files, args.fontsize)
    plot_combined_avg_weights(series, valid_families, styles, args.outdir, prefix, total_files, args.fontsize)

    family_outdir = args.outdir / "families"
    ensure_dir(family_outdir)
    for family in valid_families:
        style = styles.get(family)
        if style is None:
            continue
        plot_family_curves(series, family, style, family_outdir, prefix, args.fontsize)

    print(f"Wrote plots to {args.outdir}")
    print(f"Legend ID map: {id_map_path}")


if __name__ == "__main__":
    main()
