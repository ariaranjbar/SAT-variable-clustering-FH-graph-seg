"""Shared plotting style utilities for benchmark visualizations."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import blake2b
from typing import Any, Dict, Iterable, List, Tuple

import seaborn as sns

sns.set_context("talk", font_scale=0.85)
sns.set_style("whitegrid")

# Keep palettes deterministic so identical family strings map to the same style.
COLOR_PALETTE = sns.color_palette("tab20", n_colors=20)

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


def _stable_index(key: str, length: int, *, salt: str = "", seed: int = 0) -> int:
    """Return a deterministic index for *key* in [0, length)."""
    digest = blake2b(f"{seed}:{salt}:{key}".encode("utf-8"), digest_size=4).digest()
    value = int.from_bytes(digest, byteorder="big", signed=False)
    return value % length if length else 0


def build_family_styles(families: Iterable[str], *, seed: int = 0) -> Dict[str, FamilyStyle]:
    """Assign deterministic color/line/marker triplets to each family name.
    
    Args:
        families: Iterable of family name strings.
        seed: Optional seed to reshuffle style assignments while maintaining determinism.
    """
    unique = sorted(set(families))
    styles: Dict[str, FamilyStyle] = {}
    for family in unique:
        color = COLOR_PALETTE[_stable_index(family, len(COLOR_PALETTE), seed=seed)]
        linestyle = LINESTYLES[_stable_index(family, len(LINESTYLES), salt="linestyle", seed=seed)]
        marker = MARKERS[_stable_index(family, len(MARKERS), salt="marker", seed=seed)]
        styles[family] = FamilyStyle(color=color, linestyle=linestyle, marker=marker)
    return styles
