"""Extract SAT benchmark hashes by family.

This script reads a meta.csv file with SAT benchmark metadata and returns
hash identifiers for the requested families as a JSON array. The list of
families is sourced from a JSON file to keep command invocations concise."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence


DEFAULT_FAMILIES_JSON = (
    Path(__file__).resolve().parent / "families.json"
)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Return hashes from a SAT competition meta.csv for selected families.",
    )
    parser.add_argument(
        "meta_csv",
        type=Path,
        help="Path to the meta.csv file to scan.",
    )
    parser.add_argument(
        "-n",
        "--limit-per-family",
        type=int,
        dest="limit",
        default=None,
        help="Maximum number of hashes to return for each family.",
    )
    parser.add_argument(
        "-f",
        "--families-json",
        type=Path,
        default=DEFAULT_FAMILIES_JSON,
        help="Path to a JSON file containing a 'families' array (default: repository copy).",
    )
    return parser.parse_args(argv)


def collect_hashes(
    csv_path: Path,
    families: Iterable[str],
    limit_per_family: Optional[int] = None,
) -> List[str]:
    if limit_per_family is not None and limit_per_family < 1:
        raise ValueError("limit per family must be a positive integer")

    family_lookup = {family.lower(): family for family in families}
    target_families = set(family_lookup)
    counts: defaultdict[str, int] = defaultdict(int)
    hashes: List[str] = []
    seen_families: set[str] = set()

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"hash", "family"}
        missing_columns = required_columns - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"meta.csv missing required columns: {', '.join(sorted(missing_columns))}"
            )

        for row in reader:
            family = (row.get("family") or "").strip()
            family_key = family.lower()
            if family_key not in target_families:
                continue

            seen_families.add(family_key)
            if limit_per_family is not None and counts[family_key] >= limit_per_family:
                continue

            hash_value = (row.get("hash") or "").strip()
            if not hash_value:
                continue

            hashes.append(hash_value)
            counts[family_key] += 1

    missing = target_families - seen_families
    if missing:
        missing_names = ", ".join(family_lookup[key] for key in sorted(missing))
        print(f"Warning: no entries found for families: {missing_names}", file=sys.stderr)

    return hashes


def load_families(families_path: Path) -> List[str]:
    try:
        raw_content = families_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"families file not found: {families_path}") from exc

    try:
        payload: Any = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {families_path}: {exc}") from exc

    if not isinstance(payload, dict) or "families" not in payload:
        raise ValueError(f"expected object with 'families' list in {families_path}")

    families = payload["families"]
    if not isinstance(families, list) or not all(isinstance(f, str) for f in families):
        raise ValueError(f"'families' must be a list of strings in {families_path}")

    return families


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        families = load_families(args.families_json)
        hashes = collect_hashes(args.meta_csv, families, args.limit)
    except Exception as exc:  # noqa: BLE001 - surface error messages to users
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    json.dump(hashes, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
