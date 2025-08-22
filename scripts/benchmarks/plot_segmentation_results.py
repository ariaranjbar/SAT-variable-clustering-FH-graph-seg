#!/usr/bin/env python3
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
    for col in ["k", "threads", "comps", "vars", "edges"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ["keff", "gini", "pmax", "entropyJ", "total_sec", "parse_sec", "vig_build_sec", "seg_sec", "agg_memory"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "file" in df.columns:
        df["file"] = df["file"].astype(str)
    if "impl" in df.columns:
        df["impl"] = df["impl"].astype(str)

    # Derived columns
    # seg over parse runtime, guard against zero/NaN parse_sec
    parsing_pos = df["parse_sec"].where(df["parse_sec"] > 0)
    df["seg_frac"] = df["seg_sec"] / parsing_pos
    seg_frac_mean = df.groupby("file", observed=True)["seg_frac"].transform("mean")
    seg_frac_mean = seg_frac_mean.where(seg_frac_mean > 0)
    df["seg_frac"] = df["seg_frac"] / seg_frac_mean

    # Memory fraction per file (use per-file mean of agg_memory), guard against non-positive mean
    if "agg_memory" in df.columns:
        file_mean_mem = df.groupby("file", observed=True)["agg_memory"].transform("mean")
        file_mean_mem = file_mean_mem.where(file_mean_mem > 0)
        df["mem_frac"] = df["agg_memory"] / file_mean_mem
    else:
        df["mem_frac"] = np.nan

    # Components fraction per file (use per-file mean)
    if "comps" in df.columns:
        file_mean_comps = df.groupby("file", observed=True)["comps"].transform("mean")
        file_mean_comps = file_mean_comps.where(file_mean_comps > 0)
        df["comps_frac"] = df["comps"] / file_mean_comps
    else:
        df["comps_frac"] = np.nan

    # Tau labels and order
    _ = tau_label_and_order(df)
    return df


def pivot_tau_k_mean(df: pd.DataFrame, value_col: str, tau_order: List[str]) -> pd.DataFrame:
    """Group by (tau_label, k) and compute mean of value_col; return pivoted table."""
    d = df.dropna(subset=["tau_label", "k", value_col]).copy()
    d["k"] = pd.to_numeric(d["k"], errors="coerce")
    # average across files/threads/etc. for each (tau, k)
    g = d.groupby(["tau_label", "k"], observed=True)[value_col].mean().reset_index()
    pt = g.pivot(index="tau_label", columns="k", values=value_col)
    # Sort axes
    if tau_order:
        pt = pt.reindex(tau_order)
    k_order = sorted([c for c in pt.columns if pd.notna(c)])
    pt = pt.reindex(columns=k_order)
    return pt


def plot_heatmap(pt: pd.DataFrame, title: str, cbar_label: str, outpath: str, cmap: str = "mako"):
    if pt.dropna(how="all").empty:
        return
    plt.figure(figsize=(8, 6))
    ax = sns.heatmap(pt, cmap=cmap, linewidths=0.5, linecolor="white", cbar_kws={"label": cbar_label}, robust=True)
    ax.set_title(title)
    ax.set_xlabel("k")
    ax.set_ylabel("tau")
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def main():
    ap = argparse.ArgumentParser(description="Plot segmentation results heatmaps over tau × k.")
    ap.add_argument("--csv", default="scripts/benchmarks/out/segmentation_results.csv")
    ap.add_argument("--outdir", default="scripts/benchmarks/out/segmentation_plots")
    ap.add_argument("--impl", default=None, help="Optional: filter to a specific impl (e.g., opt or naive)")
    args = ap.parse_args()

    ensure_dir(args.outdir)
    df = load(args.csv)

    # Optional impl filter
    if args.impl:
        df = df[df["impl"] == args.impl]

    tau_order = tau_label_and_order(df)

    # Heatmap 1: seg_sec as fraction of total_sec
    pt_seg = pivot_tau_k_mean(df, "seg_frac", tau_order)
    plot_heatmap(
        pt_seg,
        title="(segmentation time / parsing time) / per-file mean",
        cbar_label="mean fraction",
        outpath=os.path.join(args.outdir, "heatmap_seg_fraction_tau_k.png"),
        cmap="rocket_r",
    )

    # Heatmap 2: memory as fraction of per-file mean memory
    pt_mem = pivot_tau_k_mean(df, "mem_frac", tau_order)
    plot_heatmap(
        pt_mem,
        title="memory usage / per-file mean",
        cbar_label="mean fraction",
        outpath=os.path.join(args.outdir, "heatmap_memory_fraction_tau_k.png"),
        cmap="viridis",
    )

    # Heatmap 3: number of components as fraction of per-file mean
    pt_comps = pivot_tau_k_mean(df, "comps_frac", tau_order)
    plot_heatmap(
        pt_comps,
        title="number of components / per-file mean",
        cbar_label="mean fraction",
        outpath=os.path.join(args.outdir, "heatmap_components_fraction_tau_k.png"),
        cmap="magma",
    )

    # Optional: Visualize balance metrics if present (mean by tau×k)
    for metric, title, cmap in [
        ("keff", "effective components (keff)", "viridis"),
        ("gini", "gini coefficient", "magma"),
        ("pmax", "max component share (pmax)", "rocket_r"),
        ("entropyJ", "entropy evenness (J)", "mako"),
    ]:
        if metric in df.columns:
            pt = pivot_tau_k_mean(df, metric, tau_order)
            plot_heatmap(
                pt,
                title=title,
                cbar_label=f"mean {metric}",
                outpath=os.path.join(args.outdir, f"heatmap_{metric}_tau_k.png"),
                cmap=cmap,
            )

    print(f"Wrote plots to {args.outdir}")


if __name__ == "__main__":
    main()
