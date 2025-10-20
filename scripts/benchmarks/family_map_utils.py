#!/usr/bin/env python
"""Helpers for mapping component CSV filenames to family metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Tuple, Union

import pandas as pd

PathLike = Union[str, Path]
Color = Tuple[float, float, float]


def extract_hash_from_filename(name: str) -> str:
    """Return the leading hash segment (text before the first '-') or an empty string."""
    segment = Path(name).name
    dash = segment.find("-")
    return segment[:dash] if dash > 0 else ""


def load_family_map(meta_csv: PathLike) -> Dict[str, str]:
    """Load meta.csv and return a mapping of hash -> family."""
    df = pd.read_csv(meta_csv)
    if not {"hash", "family"}.issubset(df.columns):
        raise ValueError("meta.csv must contain 'hash' and 'family' columns")
    # Later rows win when duplicates exist to keep behaviour predictable.
    return {str(row["hash"]): str(row["family"]) for _, row in df.iterrows()}


def families_for_csvs(paths: Iterable[Path], meta_csv: PathLike) -> Dict[Path, str]:
    """Attach families to each component CSV path using meta.csv lookups."""
    fam_map = load_family_map(meta_csv)
    out: Dict[Path, str] = {}
    for path in paths:
        hsh = extract_hash_from_filename(path.name)
        out[path] = fam_map.get(hsh, "unknown")
    return out
