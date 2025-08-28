#!/usr/bin/env python
import argparse
import os
from typing import List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


sns.set_context("talk")
sns.set_style("whitegrid")


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def tau_label_and_order(df: pd.DataFrame) -> List[str]:
    """Add tau_label and tau_norm columns (∞ for -1), return ordered labels."""
    # Normalize tau to int with -1 representing infinity
    def to_norm(x):
        try:
            v = int(x)
        except Exception:
            sx = str(x).strip().lower()
            v = -1 if sx in {"-1", "inf", "infinity", "∞"} else np.nan
        return v

    df["tau_norm"] = df["tau"].apply(to_norm)
    df["tau_label"] = df["tau_norm"].apply(lambda v: "∞" if v == -1 else ("nan" if pd.isna(v) else str(int(v))))
    # Order taus numerically with infinity last
    work = df[["tau_label", "tau_norm"]].drop_duplicates().copy()
    work["sort_key"] = work["tau_norm"].apply(lambda v: float("inf") if v == -1 else v)
    work = work.sort_values("sort_key")
    return work["tau_label"].tolist()


def load(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Coerce types we need
    for col in ["threads", "vars", "edges"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["total_sec", "parse_sec", "vig_build_sec", "agg_memory"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "file" in df.columns:
        df["file"] = df["file"].astype(str)
    if "impl" in df.columns:
        df["impl"] = df["impl"].astype(str)

    # Derived columns
    # vig_build over parse runtime, guard against zero/NaN parse_sec
    parsing_pos = df["parse_sec"].where(df["parse_sec"] > 0)
    df["vig_build_frac"] = df["vig_build_sec"] / parsing_pos
    vig_build_frac_mean = df.groupby("file", observed=True)["vig_build_frac"].transform("mean")
    vig_build_frac_mean = vig_build_frac_mean.where(vig_build_frac_mean > 0)
    df["vig_build_frac"] = df["vig_build_frac"] / vig_build_frac_mean

    # Memory fraction per file (use per-file mean of agg_memory), guard against non-positive mean
    if "agg_memory" in df.columns:
        file_mean_mem = df.groupby("file", observed=True)["agg_memory"].transform("mean")
        file_mean_mem = file_mean_mem.where(file_mean_mem > 0)
        df["mem_frac"] = df["agg_memory"] / file_mean_mem
    else:
        df["mem_frac"] = np.nan

    # No components metrics in vig_info_results; nothing to compute here

    # Tau labels and order
    _ = tau_label_and_order(df)
    return df


def pivot_tau_thread_mean(df: pd.DataFrame, value_col: str, tau_order: List[str]) -> pd.DataFrame:
    """Group by (tau_label, threads) and compute mean of value_col; return pivoted table."""
    d = df.dropna(subset=["tau_label", "threads", value_col]).copy()
    d["threads"] = pd.to_numeric(d["threads"], errors="coerce")
    # average across files/threads/etc. for each (tau, threads)
    g = d.groupby(["tau_label", "threads"], observed=True)[value_col].mean().reset_index()
    pt = g.pivot(index="tau_label", columns="threads", values=value_col)
    # Sort axes
    if tau_order:
        pt = pt.reindex(tau_order)
    threads_order = sorted([c for c in pt.columns if pd.notna(c)])
    pt = pt.reindex(columns=threads_order)
    return pt


def plot_heatmap(pt: pd.DataFrame, title: str, cbar_label: str, outpath: str, cmap: str = "mako"):
    if pt.dropna(how="all").empty:
        return
    plt.figure(figsize=(8, 6))
    ax = sns.heatmap(pt, cmap=cmap, linewidths=0.5, linecolor="white", cbar_kws={"label": cbar_label}, robust=True)
    ax.set_title(title)
    ax.set_xlabel("threads")
    ax.set_ylabel("tau")
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def _plot_line_mean_by_threads(df: pd.DataFrame, value_col: str, value_col_label: str, outpath: str, title: str, hue: str = "tau_label"):
    d = df.dropna(subset=["threads", value_col]).copy()
    if d.empty:
        return
    d["threads"] = pd.to_numeric(d["threads"], errors="coerce")
    plt.figure(figsize=(9, 6))
    ax = sns.lineplot(data=d, x="threads", y=value_col, hue=hue, estimator="mean", errorbar="se")
    ax.set_title(title)
    ax.set_xlabel("thread count")
    ax.set_ylabel(value_col_label)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def _plot_reg_scatter(df: pd.DataFrame, x: str, y: str, outpath: str, title: str):
    d = df.dropna(subset=[x, y]).copy()
    if d.empty:
        return
    plt.figure(figsize=(8, 6))
    ax = sns.regplot(data=d, x=x, y=y, scatter_kws={"alpha": 0.25, "s": 20}, line_kws={"color": "red"})
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_title(title)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def _plot_corr_heatmap(df: pd.DataFrame, outpath: str, title: str, *, exclude_threads: bool = False):
    """Plot correlation heatmap limited to specific metrics with custom labels.

    Included metrics (in this order; "threads" omitted if exclude_threads=True):
    - tau (numeric; prefers tau_norm if present)
    - threads
    - vars
    - edges
    - parse_sec -> label "parsing (s)"
    - vig_build_sec -> label "vig construction (s)"
    - agg_memory -> label "memory usage"
    """
    # Desired columns and display labels (internal_name, display_label)
    desired_specs = [
        ("tau", "tau"),
        ("threads", "threads"),
        ("vars", "vars"),
        ("edges", "edges"),
        ("parse_sec", "parsing (s)"),
        ("vig_build_sec", "vig construction (s)"),
        ("agg_memory", "memory usage"),
    ]
    if exclude_threads:
        desired_specs = [spec for spec in desired_specs if spec[0] != "threads"]

    series_by_label = {}
    for name, label in desired_specs:
        if name == "tau":
            if "tau_norm" in df.columns:
                s = pd.to_numeric(df["tau_norm"], errors="coerce")
            elif "tau" in df.columns:
                s = pd.to_numeric(df["tau"], errors="coerce")
            else:
                continue
        else:
            if name not in df.columns:
                continue
            s = pd.to_numeric(df[name], errors="coerce")
        # Keep the series even if it has NaNs; correlation will handle row-wise NaNs
        if s.notna().any():
            series_by_label[label] = s

    # Need at least 2 variables to compute a correlation
    if len(series_by_label) < 2:
        return

    # Construct DataFrame with columns ordered as in desired_specs using labels
    ordered_labels = [label for _, label in desired_specs if label in series_by_label]
    num_df = pd.DataFrame({label: series_by_label[label] for label in ordered_labels})
    if num_df.empty:
        return

    corr = num_df.corr(numeric_only=True)
    if corr.isna().all().all():
        return

    # Enforce consistent ordering
    corr = corr.reindex(index=ordered_labels, columns=ordered_labels)

    plt.figure(figsize=(9, 7))
    ax = sns.heatmap(corr, cmap="coolwarm", center=0, linewidths=0.5, linecolor="white")
    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def main():
    ap = argparse.ArgumentParser(description="Plot VIG construction results heatmaps over tau × threads.")
    ap.add_argument("--csv", default="scripts/benchmarks/out/vig_info_results.csv")
    ap.add_argument("--outdir", default="scripts/benchmarks/out/vig_build_plots")
    ap.add_argument("--impl", default=None, help="Optional: filter to a specific impl (e.g., opt or naive)")
    args = ap.parse_args()

    ensure_dir(args.outdir)
    df = load(args.csv)

    # Optional impl filter
    if args.impl:
        df = df[df["impl"] == args.impl]
    # Compose plot title and filename suffix based on impl
    impl_norm = args.impl.strip().lower() if args.impl else None
    if impl_norm in {"opt", "optimized"}:
        impl_title = " [optimized]"
        impl_suffix = "_optimized"
    elif impl_norm == "naive":
        impl_title = " [naive]"
        impl_suffix = "_naive"
    else:
        impl_title = f" [impl={args.impl}]" if args.impl else ""
        impl_suffix = f"_{args.impl}" if args.impl else ""

    tau_order = tau_label_and_order(df)

    # Determine if we should omit thread-related plots (naive impl)
    naive_impl = (impl_norm == "naive") if impl_norm else False

    if not naive_impl:
        # Heatmap 1: (VIG build / parsing) / per-file mean over tau × threads
        pt_build = pivot_tau_thread_mean(df, "vig_build_frac", tau_order)
        plot_heatmap(
            pt_build,
            title="(VIG build time / parsing time) / per-file mean" + impl_title,
            cbar_label="mean fraction",
            outpath=os.path.join(args.outdir, f"heatmap_vig_build_fraction_tau_threads{impl_suffix}.png"),
            cmap="rocket_r",
        )

        # Heatmap 2: memory usage / per-file mean over tau × threads
        pt_mem = pivot_tau_thread_mean(df, "mem_frac", tau_order)
        plot_heatmap(
            pt_mem,
            title="memory usage / per-file mean" + impl_title,
            cbar_label="mean fraction",
            outpath=os.path.join(args.outdir, f"heatmap_memory_fraction_tau_threads{impl_suffix}.png"),
            cmap="viridis",
        )

    # No components heatmap for VIG info results

        # Line plot: mean VIG build fraction vs threads per tau
        _plot_line_mean_by_threads(
            df,
            value_col="vig_build_frac",
            value_col_label="VIG build / parse",
            outpath=os.path.join(args.outdir, f"line_vig_build_fraction_by_threads{impl_suffix}.png"),
            title="VIG build / parse vs threads (mean)" + impl_title,
        )

    # Correlation heatmap of numeric columns
    _plot_corr_heatmap(
        df,
        outpath=os.path.join(args.outdir, f"corr_numeric{impl_suffix}.png"),
        title="numeric feature correlation" + impl_title,
        exclude_threads=naive_impl,
    )

    print(f"Wrote plots to {args.outdir}")


if __name__ == "__main__":
    main()
