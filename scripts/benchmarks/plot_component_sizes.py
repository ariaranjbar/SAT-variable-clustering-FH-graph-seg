#!/usr/bin/env python
"""
Plot component-size coverage from *_components.csv files.

Changes vs. earlier version:
- No longer writes sorted CSV copies to disk (sorts in-memory only).
- Produces a combined coverage plot overlaying multiple files in one figure,
  color- and style-grouped by dataset family.

Conventions:
- Mirrors style of other plotting scripts (seaborn/matplotlib, argparse)
- Default input root: scripts/benchmarks/out/components
- Outputs plots under: scripts/benchmarks/out/component_size_plots

Generated plots (combined over all inputs):
- combined_topn_coverage.png: for each file, plots y = percent of total nodes in the n largest components vs x = n (log-scaled)
- combined_topn_avg_min_internal_weight.png: for each file, plots y = average min_internal_weight of the top-n components vs x = n (log-scaled)
"""
import argparse
import os
import json
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Dict, Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from family_color_map import families_for_csvs, extract_hash_from_filename


sns.set_context("talk", font_scale=0.85)
sns.set_style("whitegrid")


DEFAULT_IN_ROOT = "scripts/benchmarks/out/components"
DEFAULT_OUT_DIR = "scripts/benchmarks/out/component_size_plots"
ID_MAP_FILENAME = "combined_size_id_map.csv"
DEFAULT_RESULTS_CSV = "scripts/benchmarks/out/segmentation_results.csv"
DEFAULT_FILTER_CONFIG = "scripts/benchmarks/configs/segmentation_results_filters.example.json"

# Legend ID alphabet (a-z | A-Z | 0-9) and fixed width
_ID_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_ID_BASE = len(_ID_ALPHABET)
_ID_WIDTH = 3  # exactly three characters


def _base62_id(n: int) -> str:
    """Convert integer n to a fixed-width 3-char base62-like string using _ID_ALPHABET.
    First ID is 'aaa'. Raises if n exceeds capacity.
    """
    max_n = _ID_BASE ** _ID_WIDTH
    if n < 0 or n >= max_n:
        raise ValueError(f"ID capacity exceeded for width={_ID_WIDTH} and base={_ID_BASE}")
    chars = []
    x = n
    for _ in range(_ID_WIDTH):
        chars.append(_ID_ALPHABET[x % _ID_BASE])
        x //= _ID_BASE
    # pad with first alphabet char if needed (should always fill width)
    while len(chars) < _ID_WIDTH:
        chars.append(_ID_ALPHABET[0])
    return "".join(reversed(chars))


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def find_component_csvs(root: Path) -> List[Path]:
    return [p for p in root.rglob("*_components.csv") if p.is_file()]


def parse_labels_from_path(p: Path, in_root: Optional[Path]) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (display_name, tau, k) if recognizable from path structure.
    Expected path fragments like .../segmentation/tau_<tau>/k_<k>/<hash>-<file>_components.csv
    """
    stem = p.name
    display_name = stem
    if stem.endswith("_components.csv"):
        core = stem[:-len("_components.csv")]
        # Drop leading hash + '-' if present
        dash = core.find('-')
        display_name = core[dash+1:] if dash != -1 else core

    tau = None
    kval = None
    try:
        parts = list(p.parts)
        # Look for tau_* and k_* in parent directories
        for idx in range(len(parts)):
            el = parts[idx]
            if el.startswith("tau_"):
                tau = el.split("_", 1)[1]
            if el.startswith("k_"):
                kval = el.split("_", 1)[1]
    except Exception:
        pass

    # If we have a root and a relative subdir, prefer the filename part as display name
    if in_root is not None:
        try:
            rel = p.relative_to(in_root)
            display_name = rel.name[:-len("_components.csv")] if rel.name.endswith("_components.csv") else rel.stem
        except Exception:
            pass

    return display_name, tau, kval


def _load_sizes_and_weights(csv_path: Path) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Load component sizes and min_internal_weight arrays.
    Sizes returned as int numpy array filtered to >0. Weights returned as float array
    aligned to sizes (after filtering), or None if the column is missing.
    """
    df = pd.read_csv(csv_path)
    if "size" not in df.columns:
        return np.array([], dtype=int), None
    s = pd.to_numeric(df["size"], errors="coerce").fillna(0).astype(int)
    mask = s > 0
    sizes = s[mask].to_numpy(copy=False)
    weights: Optional[np.ndarray] = None
    if "min_internal_weight" in df.columns:
        w = pd.to_numeric(df["min_internal_weight"], errors="coerce").fillna(np.nan)
        w = w[mask]
        try:
            weights = w.to_numpy(copy=False).astype(float)
        except Exception:
            weights = w.to_numpy(copy=False)
    return sizes, weights


def _assign_ids(labels_and_paths: List[Tuple[str, Path]]) -> Dict[str, str]:
    """Deterministically assign 3-char IDs to each label based on sorted order.
    Returns mapping label -> id.
    """
    # sort by label to keep IDs stable across runs
    sorted_entries = sorted(labels_and_paths, key=lambda lp: lp[0])
    label_to_id: Dict[str, str] = {}
    for i, (label, _p) in enumerate(sorted_entries):
        label_to_id[label] = _base62_id(i)
    return label_to_id


def _write_id_map(out_dir: Path, label_to_id: Dict[str, str], label_to_path: Dict[str, Path], in_root: Optional[Path], label_sizes: Optional[Dict[str, np.ndarray]] = None, label_to_family: Optional[Dict[str, str]] = None) -> Path:
    rows = []
    for label, idv in sorted(label_to_id.items(), key=lambda kv: kv[1]):
        p = label_to_path.get(label)
        path_str: str
        if p is None:
            path_str = ""
        else:
            if in_root is not None:
                try:
                    path_str = str(p.relative_to(in_root))
                except Exception:
                    path_str = str(p)
            else:
                path_str = str(p)
        n_sizes = int(label_sizes[label].size) if (label_sizes is not None and label in label_sizes) else None
        fam = label_to_family.get(label) if label_to_family else None
        if fam is None or (isinstance(fam, float) and np.isnan(fam)) or (isinstance(fam, str) and fam.strip() == ""):
            fam = "unknown"
        rows.append({"id": idv, "label": label, "file": path_str, "family": fam, "n_sizes": n_sizes})
    df = pd.DataFrame(rows, columns=["id", "label", "file", "family", "n_sizes"])
    out_path = out_dir / ID_MAP_FILENAME
    df.to_csv(out_path, index=False)
    return out_path


def _load_filter_config(path: Optional[Path]) -> Optional[Dict[str, Dict[str, float]]]:
    """Load a simple JSON config describing numeric thresholds to keep files.
    Expected shape:
    {
      "min": {"total_sec": 1.5, ...},    # keep only if value >= threshold
      "max": {"comps": 5000, ...}        # keep only if value <= threshold
    }
    """
    if path is None:
        return None
    if not path.exists():
        # Silently skip if config not present
        return None
    with open(path, "r") as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: filter config {path} is not valid JSON; ignoring.")
            return None
    out: Dict[str, Dict[str, float]] = {}
    for key in ("min", "max"):
        vals = cfg.get(key, {}) or {}
        # ensure numeric thresholds
        out[key] = {str(k): float(v) for k, v in vals.items()}
    return out


def _load_results_index(results_csv: Path) -> Dict[str, Dict[str, float]]:
    """Index segmentation results by hash (derived from 'file' column). Returns dict[hash] -> row dict."""
    if not results_csv.exists():
        raise FileNotFoundError(f"Results CSV not found: {results_csv}")
    df = pd.read_csv(results_csv)
    if "file" not in df.columns:
        raise ValueError("segmentation_results.csv must contain a 'file' column")
    index: Dict[str, Dict[str, float]] = {}
    for _, row in df.iterrows():
        h = extract_hash_from_filename(str(row["file"]))
        if not h:
            continue
        # store values as raw; we'll coerce to numeric when comparing
        index[h] = {col: row[col] for col in df.columns}
    return index


def _row_value(row: Dict[str, float], key: str) -> Optional[float]:
    try:
        v = row.get(key)
    except Exception:
        return None
    try:
        # pd.to_numeric expects array-like or scalar; ensure scalar fallback
        try:
            return float(pd.to_numeric(v))  # type: ignore[arg-type]
        except Exception:
            try:
                return float(v)  # type: ignore[arg-type]
            except Exception:
                return None
    except Exception:
        return None


def _passes_filters(row: Dict[str, float], flt: Dict[str, Dict[str, float]]) -> bool:
    # min thresholds
    for k, thr in flt.get("min", {}).items():
        v = _row_value(row, k)
        if v is None or not (v >= thr):
            return False
    # max thresholds
    for k, thr in flt.get("max", {}).items():
        v = _row_value(row, k)
        if v is None or not (v <= thr):
            return False
    return True


def _slugify(s: str) -> str:
    """Make a safe filename slug from an arbitrary string."""
    out = []
    for ch in s:
        if ch.isalnum() or ch in ("-", "."):
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out)
    # collapse consecutive underscores
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "family"








def _make_label(csv_path: Path, in_root: Optional[Path]) -> str:
    name, tau, kval = parse_labels_from_path(csv_path, in_root)
    extras = []
    if tau is not None:
        extras.append(f"tau={tau}")
    if kval is not None:
        extras.append(f"k={kval}")
    extra_s = f" ({', '.join(extras)})" if extras else ""
    return f"{name}{extra_s}"


def main():
    ap = argparse.ArgumentParser(description="Plot combined component-size distributions from *_components.csv files.")
    ap.add_argument("--root", type=Path, default=Path(DEFAULT_IN_ROOT), help="Root directory to scan for *_components.csv (recursive)")
    ap.add_argument("--files", type=Path, nargs="*", default=None, help="Specific *_components.csv files to process (overrides --root if given)")
    ap.add_argument("--outdir", type=Path, default=Path(DEFAULT_OUT_DIR), help="Directory to write combined plots")
    ap.add_argument("--title", type=str, default=None, help="Optional plot title prefix")
    ap.add_argument("--legend-fontsize", type=float, default=7.0, help="Legend font size (points)")
    ap.add_argument("--meta", type=Path, default=Path("benchmarks/meta.csv"), help="Path to benchmarks meta.csv with hash,family columns")
    ap.add_argument("--results-csv", type=Path, default=Path(DEFAULT_RESULTS_CSV), help="Path to segmentation_results.csv for additional filtering")
    ap.add_argument("--filter-config", type=Path, default=Path(DEFAULT_FILTER_CONFIG), help="JSON file with numeric min/max thresholds against segmentation_results.csv")
    args = ap.parse_args()

    ensure_dir(args.outdir)

    csvs: List[Path]
    in_root: Optional[Path] = None
    if args.files:
        csvs = [Path(p) for p in args.files]
    else:
        in_root = Path(args.root)
        csvs = find_component_csvs(in_root)

    if not csvs:
        print("No *_components.csv files found.")
        return

    # Optional filters
    filter_cfg = _load_filter_config(args.filter_config)
    results_index: Optional[Dict[str, Dict[str, float]]] = None
    if filter_cfg:
        try:
            results_index = _load_results_index(args.results_csv)
        except Exception as e:
            print(f"Failed to load results CSV for filtering: {e}")
            results_index = None

    # Load data and prepare labels
    label_to_path: Dict[str, Path] = {}
    label_sizes: Dict[str, np.ndarray] = {}
    label_weights: Dict[str, np.ndarray] = {}
    for p in csvs:
        try:
            sizes, weights = _load_sizes_and_weights(p)
            # Discard files with 2 components or fewer before any calculations/plotting
            if sizes.size <= 2:
                print(f"Skipping {p} (only {sizes.size} components)")
                continue
            # Apply optional results-based filters
            if filter_cfg and results_index is not None:
                h = extract_hash_from_filename(p.name)
                row = results_index.get(h)
                if not row:
                    print(f"Skipping {p} (no results row for hash {h})")
                    continue
                if not _passes_filters(row, filter_cfg):
                    print(f"Skipping {p} (failed filter thresholds)")
                    continue
            label = _make_label(p, in_root)
            label_to_path[label] = p
            label_sizes[label] = sizes
            if weights is not None and np.isfinite(weights).any():
                label_weights[label] = weights
        except Exception as e:
            print(f"Failed to load {p}: {e}")

    if not label_sizes:
        print("No valid component sizes to plot.")
        return

    # Assign compact IDs per file and write map
    labels_and_paths = [(lbl, label_to_path[lbl]) for lbl in label_sizes.keys()]
    label_to_id = _assign_ids(labels_and_paths)
    # Build families for labeling later
    # Determine family per input file and color map
    id_to_path: Dict[str, Path] = {label_to_id[lbl]: label_to_path[lbl] for lbl in label_sizes.keys()}
    # families_for_csvs may expect existing meta file; guard if absent
    if args.meta.exists():
        try:
            fam_by_path = families_for_csvs(id_to_path.values(), args.meta)
        except Exception as e:
            print(f"Warning: failed to derive families from meta {args.meta}: {e}")
            fam_by_path = {p: "unknown" for p in id_to_path.values()}
    else:
        print(f"Warning: meta file {args.meta} not found; assigning 'unknown' family.")
        fam_by_path = {p: "unknown" for p in id_to_path.values()}
    id_to_family: Dict[str, str] = {idv: fam_by_path.get(p, "unknown") for idv, p in id_to_path.items()}
    label_to_family: Dict[str, str] = {lbl: id_to_family.get(label_to_id[lbl], "unknown") for lbl in label_sizes.keys()}
    id_map_path = _write_id_map(args.outdir, label_to_id, label_to_path, in_root, label_sizes, label_to_family)

    # Build series keyed by IDs for data, but color/group by family
    series: Dict[str, np.ndarray] = {label_to_id[lbl]: arr for lbl, arr in label_sizes.items()}
    series_weights: Dict[str, np.ndarray] = {label_to_id[lbl]: w for lbl, w in label_weights.items() if lbl in label_to_id}

    # id_to_family already computed above
    # Family styling: build a deterministic interleaved sequence of (color, linestyle)
    # so we don't exhaust all colors or all styles first. This diagonally mixes both.
    families_sorted = sorted(set(id_to_family.values()))
    base_colors = sns.color_palette("tab20")  # qualitative palette base
    base_len = max(1, len(base_colors))
    linestyles = [
        "-", "--", "-.", ":",
        (0, (1, 1)),        # densely dotted
        (0, (3, 1, 1, 1)),  # dash-dot-dotted
        (0, (5, 1)),        # long dash
    ]
    fam_color: Dict[str, tuple] = {}
    fam_style: Dict[str, Any] = {}
    # Build interleaved combos: for each style row, shift styles per color column
    combos: List[Tuple[tuple, Any]] = []
    m = len(linestyles)
    n = base_len
    for r in range(m):
        for c in range(n):
            combos.append((base_colors[c], linestyles[(c + r) % m]))
    for i, fam in enumerate(families_sorted):
        color, style = combos[i % len(combos)]
        fam_color[fam] = color
        fam_style[fam] = style

    n = len(series)
    prefix = args.title or "component size distribution"
    title_topn = f"{prefix} — coverage by top-n components (N={n} files)"

    topn_path = args.outdir / "combined_topn_coverage.png"
    # Plot with per-family colors and family-only legend
    plt.figure(figsize=(10, 7))
    any_data = False
    fam_handles: Dict[str, Any] = {}
    for idv, sizes in series.items():
        if sizes.size == 0:
            continue
        any_data = True
        fam = id_to_family.get(idv, "unknown")
        color = fam_color.get(fam)
        linestyle = fam_style.get(fam, "-")
        s_desc = np.sort(sizes)[::-1]
        csum = np.cumsum(s_desc)
        total = float(s_desc.sum())
        if total <= 0:
            continue
        x = np.arange(1, csum.size + 1)
        y_pct = (csum / total) * 100.0
        # Use residual percentage so log scale expands differences near 100% coverage
        y_gap = np.maximum(100.0 - y_pct, 1e-3)
        line, = plt.plot(x, y_gap, linewidth=1.5, color=color, linestyle=linestyle, alpha=0.9)
        # Create one handle per family for legend
        if fam not in fam_handles:
            fam_handles[fam] = line
    if any_data:
        plt.xscale("log")
        plt.yscale("log")  # log scale for residual percentage axis
        plt.xlabel("top-n components (n, log)")
        plt.ylabel("percent NOT covered by top-n components (log %)")
        plt.ylim(bottom=1e-3, top=100)
        plt.title(title_topn)
        # Legend: families only
        handles = [fam_handles[f] for f in sorted(fam_handles.keys())]
        labels = sorted(fam_handles.keys())
        # Place legend outside the plot on the right
        plt.legend(handles, labels,
                   loc='center left', bbox_to_anchor=(1.0, 0.5),
                   ncol=1, title='family', fontsize=args.legend_fontsize)
        plt.tight_layout()
        # Increase resolution and ensure legend is included
        plt.savefig(topn_path.as_posix(), dpi=300, bbox_inches='tight')
        plt.close()
    else:
        plt.close()

    # Combined: average min_internal_weight of top-n components
    avg_path = args.outdir / "combined_topn_avg_min_internal_weight.png"
    plt.figure(figsize=(10, 7))
    any_avg = False
    y_min_avg = np.inf
    y_max_avg = 0.0
    fam_handles_avg: Dict[str, Any] = {}
    for idv, sizes in series.items():
        weights = series_weights.get(idv)
        if sizes.size == 0 or weights is None or weights.size != sizes.size:
            continue
        any_avg = True
        fam = id_to_family.get(idv, "unknown")
        color = fam_color.get(fam)
        linestyle = fam_style.get(fam, "-")
        # sort by size desc and apply the same order to weights
        order = np.argsort(sizes)[::-1]
        s_sorted = sizes[order]
        w_sorted = weights[order].astype(float)
        x = np.arange(1, s_sorted.size + 1)
        finite_mask = np.isfinite(w_sorted)
        csum_w = np.cumsum(np.where(finite_mask, w_sorted, 0.0))
        ccount = np.cumsum(finite_mask.astype(int))
        # average of finite weights only; undefined (NaN) where count==0
        y_avg = np.divide(csum_w, ccount, out=np.full_like(csum_w, np.nan, dtype=float), where=ccount > 0)
        # track finite positive bounds for dynamic ylim
        pos = y_avg[np.isfinite(y_avg) & (y_avg > 0)]
        if pos.size > 0:
            y_min_avg = min(y_min_avg, float(np.min(pos)))
            y_max_avg = max(y_max_avg, float(np.max(pos)))
        line, = plt.plot(x, y_avg, linewidth=1.5, color=color, linestyle=linestyle, alpha=0.9)
        if fam not in fam_handles_avg:
            fam_handles_avg[fam] = line
    if any_avg:
        plt.xscale("log")
        plt.yscale("log")
        plt.xlabel("top-n components (n, log)")
        plt.ylabel("average min_internal_weight of top-n components (log)")
        if np.isfinite(y_min_avg) and y_max_avg > 0:
            bottom = y_min_avg / 1.25
            top = y_max_avg * 1.1
            if bottom <= 0:
                bottom = y_min_avg
            if top <= bottom:
                top = bottom * 1.1
            plt.ylim(bottom=bottom, top=top)
        plt.title(f"{prefix} — avg min_internal_weight by top-n components (N={n} files)")
        handles = [fam_handles_avg[f] for f in sorted(fam_handles_avg.keys())]
        labels = sorted(fam_handles_avg.keys())
        plt.legend(handles, labels,
                   loc='center left', bbox_to_anchor=(1.0, 0.5),
                   ncol=1, title='family', fontsize=args.legend_fontsize)
        plt.tight_layout()
        plt.savefig(avg_path.as_posix(), dpi=300, bbox_inches='tight')
        plt.close()
    else:
        plt.close()

    # Per-family plots (legend lists file IDs)
    family_outdir = args.outdir / "families"
    ensure_dir(family_outdir)
    for fam in families_sorted:
        fam_ids = [idv for idv, f in id_to_family.items() if f == fam]
        if not fam_ids:
            continue
        plt.figure(figsize=(10, 7))
        any_family = False
        for idx, idv in enumerate(sorted(fam_ids)):
            sizes = series.get(idv)
            if sizes is None or sizes.size == 0:
                continue
            any_family = True
            s_desc = np.sort(sizes)[::-1]
            csum = np.cumsum(s_desc)
            total = float(s_desc.sum())
            if total <= 0:
                continue
            x = np.arange(1, csum.size + 1)
            y_pct = (csum / total) * 100.0
            y_gap = np.maximum(100.0 - y_pct, 1e-3)
            linestyle = linestyles[idx % len(linestyles)]
            plt.plot(x, y_gap, linewidth=1.3, color=fam_color.get(fam), linestyle=linestyle, alpha=0.9, label=idv)
        if any_family:
            plt.xscale("log")
            plt.yscale("log")
            plt.xlabel("top-n components (n, log)")
            plt.ylabel("percent NOT covered by top-n components (log %)")
            plt.ylim(bottom=1e-3, top=100)
            fam_title = f"{prefix} — {fam} (N={len(fam_ids)} files)"
            plt.title(fam_title)
            # Place legend outside the plot on the right
            plt.legend(loc='center left', bbox_to_anchor=(1.0, 0.5), ncol=1, title='file id', fontsize=args.legend_fontsize)
            plt.tight_layout()
            outp = family_outdir / f"topn_coverage_{_slugify(fam)}.png"
            plt.savefig(outp.as_posix(), dpi=300, bbox_inches='tight')
            plt.close()
        else:
            plt.close()

        # Per-family: average min_internal_weight of top-n components
        plt.figure(figsize=(10, 7))
        any_family_avg = False
        y_min_avg_fam = np.inf
        y_max_avg_fam = 0.0
        plotted_avg = 0
        for idx, idv in enumerate(sorted(fam_ids)):
            sizes = series.get(idv)
            weights = series_weights.get(idv)
            if sizes is None or sizes.size == 0 or weights is None or weights.size != sizes.size:
                continue
            any_family_avg = True
            plotted_avg += 1
            order = np.argsort(sizes)[::-1]
            s_sorted = sizes[order]
            w_sorted = weights[order].astype(float)
            x = np.arange(1, s_sorted.size + 1)
            finite_mask = np.isfinite(w_sorted)
            csum_w = np.cumsum(np.where(finite_mask, w_sorted, 0.0))
            ccount = np.cumsum(finite_mask.astype(int))
            y_avg = np.divide(csum_w, ccount, out=np.full_like(csum_w, np.nan, dtype=float), where=ccount > 0)
            pos = y_avg[np.isfinite(y_avg) & (y_avg > 0)]
            if pos.size > 0:
                y_min_avg_fam = min(y_min_avg_fam, float(np.min(pos)))
                y_max_avg_fam = max(y_max_avg_fam, float(np.max(pos)))
            linestyle = linestyles[idx % len(linestyles)]
            plt.plot(x, y_avg, linewidth=1.3, color=fam_color.get(fam), linestyle=linestyle, alpha=0.9, label=idv)
        if any_family_avg:
            plt.xscale("log")
            plt.yscale("log")
            plt.xlabel("top-n components (n, log)")
            plt.ylabel("average min_internal_weight of top-n components (log)")
            if np.isfinite(y_min_avg_fam) and y_max_avg_fam > 0:
                bottom = y_min_avg_fam / 1.25
                top = y_max_avg_fam * 1.1
                if bottom <= 0:
                    bottom = y_min_avg_fam
                if top <= bottom:
                    top = bottom * 1.1
                plt.ylim(bottom=bottom, top=top)
            fam_title = f"{prefix} — {fam} avg min_internal_weight (N={plotted_avg} files)"
            plt.title(fam_title)
            plt.legend(loc='center left', bbox_to_anchor=(1.0, 0.5), ncol=1, title='file id', fontsize=args.legend_fontsize)
            plt.tight_layout()
            outp = family_outdir / f"topn_avg_min_internal_weight_{_slugify(fam)}.png"
            plt.savefig(outp.as_posix(), dpi=300, bbox_inches='tight')
            plt.close()
        else:
            plt.close()

    print(f"Wrote plots to {args.outdir}")
    print(f"Legend ID map: {id_map_path}")


if __name__ == "__main__":
    main()
