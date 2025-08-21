#!/usr/bin/env python3
import argparse
import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

sns.set_context("talk")
sns.set_style("whitegrid")


def coerce_tau(x: str):
    try:
        return int(x)
    except Exception:
        return -1 if str(x).strip().lower() == 'inf' or str(x).strip() == '-1' else np.nan


def load(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # Normalize types
    df['tau_norm'] = df['tau'].apply(lambda x: -1 if x == -1 else (int(x) if str(x).isdigit() else -1))
    df['tau_label'] = df['tau_norm'].apply(lambda x: '∞' if x == -1 else str(x))
    df['impl'] = df['impl'].astype(str)
    df['threads'] = pd.to_numeric(df['threads'], errors='coerce').fillna(1).astype(int)
    # Use vig_build_sec as the primary runtime metric
    if 'vig_build_sec' in df.columns:
        df['vig_build_sec'] = pd.to_numeric(df['vig_build_sec'], errors='coerce')
    else:
        # Backward compatibility if older CSVs exist
        df['vig_build_sec'] = pd.to_numeric(df.get('time_sec', np.nan), errors='coerce')
    df['edges'] = pd.to_numeric(df['edges'], errors='coerce')
    df['agg_memory'] = pd.to_numeric(df['agg_memory'], errors='coerce')
    df['file'] = df['file'].astype(str)
    return df


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def tau_order_from_df(df: pd.DataFrame):
    """Return tau labels sorted numerically ascending with 'inf' last.
    Expects columns tau_label and tau_norm (with -1 meaning inf).
    """
    if 'tau_label' not in df.columns:
        return []
    work = df[['tau_label']].drop_duplicates().copy()
    if 'tau_norm' in df.columns:
        # Merge tau_norm for sorting
        tn = df[['tau_label', 'tau_norm']].drop_duplicates()
        work = work.merge(tn, on='tau_label', how='left')
    else:
        # Fallback: derive tau_norm from label
        def to_norm(lbl: str):
            try:
                return int(lbl)
            except Exception:
                return -1 if str(lbl).strip().lower() == 'inf' or str(lbl).strip() == '-1' else np.nan
        work['tau_norm'] = work['tau_label'].apply(to_norm)
    work['sort_key'] = work['tau_norm'].apply(lambda v: float('inf') if v == -1 else v)
    work = work.sort_values('sort_key')
    return work['tau_label'].tolist()


def plot_runtime_vs_tau(df: pd.DataFrame, outdir: str):
    # Per-impl runtime vs tau (aggregated across files): median and IQR
    for impl in ['naive', 'opt']:
        d = df[df['impl'] == impl].copy()
        if d.empty:
            continue
        order = tau_order_from_df(d)
        if order:
            d['tau_label'] = pd.Categorical(d['tau_label'], categories=order, ordered=True)
        grouped = (
            d.groupby(['tau_label'], observed=True)
             .agg(
                 median_time=('vig_build_sec', 'median'),
                 p25=('vig_build_sec', lambda x: np.percentile(x, 25)),
                 p75=('vig_build_sec', lambda x: np.percentile(x, 75)),
                 count=('vig_build_sec', 'count'),
             )
             .reset_index()
             .sort_values('tau_label')
        )
        # Use numeric x positions with string tick labels to ensure ordering works for fill_between
        x = np.arange(len(grouped))
        labels = grouped['tau_label'].astype(str)
        plt.figure(figsize=(7, 5))
        plt.fill_between(x, grouped['p25'], grouped['p75'], alpha=0.2, label='IQR')
        plt.plot(x, grouped['median_time'], marker='o', label='median')
        plt.title(f"Runtime vs tau ({impl})")
        plt.xlabel('tau (max clause size)')
        plt.xticks(x, labels)
        plt.ylabel('time (s)')
        plt.legend()
        plt.tight_layout()
        plt.savefig(os.path.join(outdir, f"runtime_vs_tau_{impl}.png"), dpi=150)
        plt.close()


def plot_opt_scaling_threads(df: pd.DataFrame, outdir: str):
    # For opt only: median runtime per tau across threads
    d = df[(df['impl'] == 'opt') & (df['threads'] > 0)].copy()
    if d.empty:
        return
    # Warn if any non-positive times exist
    if (d['vig_build_sec'] <= 0).any():
        bad = d[d['vig_build_sec'] <= 0][['file','tau_label','threads','vig_build_sec']].head(10)
        print("[warn] Non-positive vig_build_sec rows detected (showing up to 10):")
        print(bad.to_string(index=False))
    # Aggregate data used by the line plot and save for inspection
    agg = (
       d.groupby(['threads','tau_label'], observed=True)
        .agg(median_time=('vig_build_sec','median'),
            sd_time=('vig_build_sec','std'),
            count=('vig_build_sec','count'),
            min_time=('vig_build_sec','min'),
            max_time=('vig_build_sec','max'))
        .reset_index()
    )
    # # Save aggregated data to CSV for debugging/inspection
    # os.makedirs(outdir, exist_ok=True)
    # agg_path = os.path.join(outdir, 'opt_scaling_threads_data.csv')
    # try:
    #     agg.sort_values(['tau_label','threads']).to_csv(agg_path, index=False)
    #     print(f"[info] Wrote aggregated opt scaling data to {agg_path}")
    # except Exception as e:
    #     print(f"[warn] Could not write aggregated data CSV: {e}")
    hue_order = tau_order_from_df(d)
    plt.figure(figsize=(8,5))
    sns.lineplot(data=d, x='threads', y='vig_build_sec', hue='tau_label', hue_order=hue_order or None,
                 estimator='median', errorbar='sd', marker='o')
    plt.title('Optimized runtime scaling vs threads')
    plt.xlabel('threads')
    plt.ylabel('time (s)')
    # Time cannot be negative; clamp y lower bound at 0 for readability
    try:
        ymin, ymax = plt.ylim()
        if ymin < 0:
            plt.ylim(bottom=0)
    except Exception:
        pass
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "opt_scaling_threads.png"), dpi=150)
    plt.close()


def plot_speedup_opt_vs_naive(df: pd.DataFrame, outdir: str):
    # Compare opt (threads=max in dataset) vs naive, per file and tau
    # For each (file, tau), take naive time and best opt time (min across threads)
    naive = df[df['impl'] == 'naive'][['file','tau_label','vig_build_sec']].rename(columns={'vig_build_sec':'t_naive'})
    opt = df[df['impl'] == 'opt'][['file','tau_label','threads','vig_build_sec']]
    best_opt = opt.groupby(['file','tau_label']).agg(t_opt=('vig_build_sec','min')).reset_index()
    j = pd.merge(naive, best_opt, on=['file','tau_label'], how='inner')
    if j.empty:
        return
    order = tau_order_from_df(j)
    if order:
        j['tau_label'] = pd.Categorical(j['tau_label'], categories=order, ordered=True)
    j['speedup'] = j['t_naive'] / j['t_opt']
    mean_speedup = float(j['speedup'].mean()) if not j['speedup'].empty else 1.0
    plt.figure(figsize=(8,5))
    ax = sns.boxplot(data=j, x='tau_label', y='speedup', order=order or None)
    sns.stripplot(data=j, x='tau_label', y='speedup', order=order or None, color='black', alpha=0.4, size=3)
    # Add horizontal line at y=1 and at the average speedup across all datapoints
    plt.axhline(1, color='red', linestyle='--', linewidth=1, label='1× baseline')
    avg_label = f'{mean_speedup:.2f}× avg'
    plt.axhline(mean_speedup, color='green', linestyle='-.', linewidth=1, label=avg_label)
    # Add legend for baseline
    handles, labels = plt.gca().get_legend_handles_labels()
    if '1× baseline' not in labels:
        handles.append(plt.Line2D([0], [0], color='red', linestyle='--', linewidth=1))
        labels.append('1× baseline')
    if avg_label not in labels:
        handles.append(plt.Line2D([0], [0], color='green', linestyle='-.', linewidth=1))
        labels.append(avg_label)
    plt.legend(handles, labels)
    # Annotate sample size above each box
    # Compute sample sizes per tau_label
    counts = j.groupby('tau_label', observed=True)['speedup'].count()
    # Get x positions for each tau_label in order
    xticks = ax.get_xticks()
    for i, tau in enumerate(order or counts.index):
        n = counts.get(tau, 0)
        # Find the max y for this box to place annotation above
        subset = j[j['tau_label'] == tau]['speedup']
        if not subset.empty:
            y_max = subset.max()
        else:
            y_max = 1
        ax.annotate(f'n={n}', xy=(xticks[i], y_max + 0.1), xycoords=('data','data'), ha='center', va='bottom', fontsize=10, color='blue')
    plt.title('Speedup: naive / best opt (lower is slower, >1 is faster)')
    plt.xlabel('tau')
    plt.ylabel('speedup (×)')
    plt.tight_layout()
    plt.savefig(os.path.join(outdir, "speedup_opt_vs_naive.png"), dpi=150)
    plt.close()


def plot_edges_and_mem(df: pd.DataFrame, outdir: str):
    # Edges vs tau and agg_memory vs tau (opt only; naive similar but less interesting)
    for metric, ylabel in [('edges', 'edges'), ('agg_memory', 'aggregation memory (bytes)')]:
        d = df[df['impl'] == 'opt'].copy()
        if d.empty:
            continue
        order = tau_order_from_df(d)
        plt.figure(figsize=(8, 5))
        sns.boxplot(data=d, x='tau_label', y=metric, order=order or None)
        plt.title(f'{ylabel} vs tau (opt)')
        plt.xlabel('tau')
        plt.ylabel(ylabel)
        plt.tight_layout()
        fname = f"{metric}_vs_tau_opt.png"
        plt.savefig(os.path.join(outdir, fname), dpi=150)
        plt.close()


def plot_tau_threads_heatmaps(df: pd.DataFrame, outdir: str):
    """Heatmaps for opt-only: tau × threads -> median time, and median agg_memory."""
    d = df[(df['impl'] == 'opt') & (df['threads'] > 0)].copy()
    if d.empty:
        return
    tau_order = tau_order_from_df(d)
    thread_order = sorted(d['threads'].unique())
    # Prepare metrics: (column, label, filename, colormap)
    metrics = [
        ('vig_build_sec', 'median VIG construction time (s)', 'heatmap_time_tau_threads_opt.png', 'mako'),
        ('agg_memory_mb', 'median agg_memory (MB)', 'heatmap_agg_memory_tau_threads_opt.png', 'viridis'),
    ]
    # Compute agg_memory_mb if needed
    if 'agg_memory_mb' not in d.columns:
        d['agg_memory_mb'] = d['agg_memory'] / (1024 * 1024)
    for col, cbar_label, fname, cmap in metrics:
        pt = (
            d.groupby(['tau_label', 'threads'], observed=True)[col]
             .median()
             .unstack('threads')
        )
        if tau_order:
            pt = pt.reindex(tau_order)
        pt = pt.reindex(columns=thread_order)
        if not pt.dropna(how='all').empty:
            plt.figure(figsize=(8, 6))
            ax = sns.heatmap(pt, cmap=cmap, linewidths=0.5, linecolor='white', cbar_kws={'label': cbar_label}, robust=True)
            ax.set_title(f'Opt {cbar_label} by tau × threads')
            ax.set_xlabel('threads')
            ax.set_ylabel('tau')
            plt.tight_layout()
            plt.savefig(os.path.join(outdir, fname), dpi=150)
            plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='scripts/benchmarks/out/results.csv')
    ap.add_argument('--outdir', default='scripts/benchmarks/out/plots')
    args = ap.parse_args()

    ensure_dir(args.outdir)
    df = load(args.csv)

    # Basic sanity: drop any rows with missing time
    df = df.dropna(subset=['vig_build_sec'])

    plot_runtime_vs_tau(df, args.outdir)
    plot_opt_scaling_threads(df, args.outdir)
    plot_speedup_opt_vs_naive(df, args.outdir)
    plot_edges_and_mem(df, args.outdir)
    plot_tau_threads_heatmaps(df, args.outdir)

    print(f"Wrote plots to {args.outdir}")

if __name__ == '__main__':
    main()
