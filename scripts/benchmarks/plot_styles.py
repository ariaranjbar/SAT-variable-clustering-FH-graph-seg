"""Shared plotting style utilities for benchmark visualizations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

import seaborn as sns

sns.set_context("talk", font_scale=0.85)
sns.set_style("whitegrid")

LINESTYLES: List[Any] = [
    "-",
    "--",
    "-.",
    ":",
    (0, (1, 1)),
    (0, (3, 1, 1, 1)),
    (0, (5, 1)),
]
MARKERS: List[str] = ["o", "s", "D", "^", "v", "P", "X", "*", ">", "<", "h", "H"]


@dataclass(frozen=True)
class FamilyStyle:
    color: Tuple[float, float, float]
    linestyle: Any
    marker: str


def build_family_styles(families: Iterable[str]) -> Dict[str, FamilyStyle]:
    """Assign color/line/marker triplets to each family name."""
    unique = sorted(set(families))
    palette = sns.color_palette("tab20", n_colors=max(1, len(unique)))
    styles: Dict[str, FamilyStyle] = {}
    for idx, family in enumerate(unique):
        color = palette[idx % len(palette)]
        linestyle = LINESTYLES[idx % len(LINESTYLES)]
        marker = MARKERS[idx % len(MARKERS)]
        styles[family] = FamilyStyle(color=color, linestyle=linestyle, marker=marker)
    return styles
