#!/usr/bin/env python3
"""
Utilities to map component CSV filenames to dataset families (via benchmarks/meta.csv)
and assign stable colors per family.

Functions:
- extract_hash_from_filename(name: str) -> str
- load_family_map(meta_csv: Union[str, Path]) -> Dict[str, str]
- families_for_csvs(paths: Iterable[Path], meta_csv: Union[str, Path]) -> Dict[Path, str]
- build_family_colors(families: Iterable[str], palette: str = "tab20") -> Dict[str, tuple]
"""
from pathlib import Path
from typing import Dict, Iterable, Union

import pandas as pd
import seaborn as sns


def extract_hash_from_filename(name: str) -> str:
    """Return substring up to the first '-' (excluded). If no '-', return empty string."""
    s = Path(name).name
    idx = s.find("-")
    return s[:idx] if idx > 0 else ""


def load_family_map(meta_csv: Union[str, Path]) -> Dict[str, str]:
    df = pd.read_csv(meta_csv)
    if not {"hash", "family"}.issubset(df.columns):
        raise ValueError("meta.csv must contain 'hash' and 'family' columns")
    # Prefer last occurrence if duplicates
    fam_map: Dict[str, str] = {str(row["hash"]): str(row["family"]) for _, row in df.iterrows()}
    return fam_map


def families_for_csvs(paths: Iterable[Path], meta_csv: Union[str, Path]) -> Dict[Path, str]:
    fam_map = load_family_map(meta_csv)
    out: Dict[Path, str] = {}
    for p in paths:
        h = extract_hash_from_filename(p.name)
        fam = fam_map.get(h, "unknown")
        out[p] = fam
    return out


def build_family_colors(families: Iterable[str], palette: str = "tab20") -> Dict[str, tuple]:
    fams = sorted(set(families))
    colors = sns.color_palette(palette, n_colors=max(1, len(fams)))
    return {fam: colors[i % len(colors)] for i, fam in enumerate(fams)}
