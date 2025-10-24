#!/usr/bin/env python
"""
Analyze benchmark CSV results and extract top argument combinations per file.

Example usage:
    # Show top 5 per CNF file for segmentation
    ./analyze_results.py top --algo segmentation --csv ../out/segmentation_results.csv --top 5

    # Filter to tau=inf and impl=opt and show top 3 per file (min-time)
    ./analyze_results.py top --algo segmentation --csv ../out/segmentation_results.csv --filter tau=inf --filter impl=opt --top 3 --sort-key total_sec --asc

    # Select a subset of columns to display
    ./analyze_results.py top --algo segmentation --csv ../out/segmentation_results.csv --show file,modularity,k,tau,impl

Outputs a simple table to stdout; optionally emit JSON or CSV.
"""
from __future__ import annotations
import argparse
import sys
import csv
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple, Iterable, Set

# Known non-parameter columns (metrics, identifiers, timings)
NON_PARAM_COMMON: Set[str] = {
    # identifiers
    "file",
    "file_id",
    "memlimit_mb",
    # graph stats
    "vars",
    "clauses",
    "edges",
    "comps",
    # objective/metrics
    "modularity",
    "keff",
    "gini",
    "pmax",
    "entropyJ",
    # timings/memory
    "total_sec",
    "parse_sec",
    "vig_build_sec",
    "seg_sec",
    "agg_memory",
}

# Try to parse values to numeric when reasonable
NUMERIC_KEYS_COMMON: Set[str] = {
    "memlimit_mb",
    "vars",
    "clauses",
    "edges",
    "comps",
    "modularity",
    "keff",
    "gini",
    "pmax",
    "entropyJ",
    "total_sec",
    "parse_sec",
    "vig_build_sec",
    "seg_sec",
    "agg_memory",
}

def load_csv(paths: List[Path]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    missing: List[Path] = []
    for p in paths:
        try:
            with p.open("r", newline="") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    rows.append(dict(r))
        except FileNotFoundError:
            missing.append(p)
    if missing:
        missing_str = ", ".join(str(p) for p in missing)
        raise FileNotFoundError(f"CSV path(s) not found: {missing_str}")
    return rows


def coerce_types(rows: List[Dict[str, Any]], numeric_hint: Set[str] | None = None) -> None:
    # Try to coerce numeric fields (from common metrics and provided hints); leave others as-is
    if not rows:
        return
    numeric_like = set(NUMERIC_KEYS_COMMON)
    if numeric_hint:
        numeric_like.update(numeric_hint)
    for r in rows:
        for k in list(r.keys()):
            v = r[k]
            if v is None:
                continue
            # strip spaces
            if isinstance(v, str):
                v = v.strip()
            # empty stays empty
            if v == "":
                r[k] = v
                continue
            try:
                if k in numeric_like:
                    # ints when possible
                    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
                        r[k] = int(v)
                    else:
                        r[k] = float(v)
                else:
                    # best-effort numeric parse; fall back to string on error
                    r[k] = float(v)
            except Exception:
                r[k] = v


def load_algorithms_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open("r") as f:
        data = json.load(f)
    algos: Dict[str, Any] = {}
    for entry in data.get("algorithms", []):
        name = entry.get("name")
        if name:
            algos[name] = entry
    return algos


def detect_algo(rows: List[Dict[str, Any]], algo_hint: str | None, algos: Dict[str, Any]) -> str:
    if algo_hint and algo_hint in algos:
        return algo_hint
    if not rows:
        # fallback: first available
        return next(iter(algos.keys()))
    cols = set(rows[0].keys())
    best_name = None
    best_overlap = -1
    for name, entry in algos.items():
        header = set(entry.get("csv", {}).get("header", []))
        overlap = len(cols & header)
        if overlap > best_overlap:
            best_overlap = overlap
            best_name = name
    return best_name or next(iter(algos.keys()))


def param_columns_from_header(header: Iterable[str]) -> List[str]:
    cols = [c for c in header if c not in NON_PARAM_COMMON]
    # Always exclude empty or None
    return [c for c in cols if c]


def param_columns_for_algo(algo_entry: Dict[str, Any], actual_cols: Iterable[str], user_param_cols: List[str] | None) -> List[str]:
    actual_cols = list(actual_cols)
    if user_param_cols:
        return [c for c in user_param_cols if c in actual_cols]
    header = algo_entry.get("csv", {}).get("header", [])
    if not header:
        header = actual_cols
    params = param_columns_from_header(header)
    # keep only those present in actual
    return [c for c in params if c in actual_cols]


def apply_filters(rows: List[Dict[str, Any]], filters: List[str]) -> List[Dict[str, Any]]:
    if not filters:
        return rows

    def match(r: Dict[str, Any]) -> bool:
        for f in filters:
            if "=" not in f:
                continue
            k, vals = f.split("=", 1)
            k = k.strip()
            # support comma-separated values
            wanted = [v.strip() for v in vals.split(",")]
            rv = r.get(k)
            if rv is None:
                return False
            # compare as string and as native type
            rv_str = str(rv)
            if rv_str in wanted or rv in wanted:
                continue
            return False
        return True

    return [r for r in rows if match(r)]


def group_by_file(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    # Prefer 'file' if present, else fall back to 'file_id'
    id_col = None
    if rows:
        first_cols = rows[0].keys()
        if "file" in first_cols:
            id_col = "file"
        elif "file_id" in first_cols:
            id_col = "file_id"
    for r in rows:
        if id_col is None:
            # fallback per-row just in case of inconsistent headers
            id_col = "file" if "file" in r else ("file_id" if "file_id" in r else None)
        key = str(r.get(id_col or "file", ""))
        groups.setdefault(key, []).append(r)
    return groups


def param_signature(row: Dict[str, Any], param_cols: List[str]) -> Tuple:
    return tuple((c, row.get(c)) for c in param_cols)


def _coerce_sort_value(value: Any, descending: bool) -> float:
    if value is None:
        return float("-inf") if descending else float("inf")
    try:
        return float(value)
    except Exception:
        return float("-inf") if descending else float("inf")


def top_per_file(rows: List[Dict[str, Any]], top_n: int, param_cols: List[str], sort_key: str, descending: bool, dedup_params: bool) -> Dict[str, List[Dict[str, Any]]]:
    groups = group_by_file(rows)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for f, rs in groups.items():
        # Optional: deduplicate by param signature keeping best score
        if dedup_params:
            best_by_sig: Dict[Tuple, Dict[str, Any]] = {}
            for r in rs:
                sig = param_signature(r, param_cols)
                cur = best_by_sig.get(sig)
                score = _coerce_sort_value(r.get(sort_key), descending)
                if cur is None:
                    best_by_sig[sig] = r
                else:
                    cur_score = _coerce_sort_value(cur.get(sort_key), descending)
                    if (score > cur_score) if descending else (score < cur_score):
                        best_by_sig[sig] = r
            rs = list(best_by_sig.values())
        # Sort and take top N
        def sortval(r: Dict[str, Any]):
            return _coerce_sort_value(r.get(sort_key), descending)
        rs.sort(key=sortval, reverse=descending)
        out[f] = rs[:top_n]
    return out


def print_table(groups: Dict[str, List[Dict[str, Any]]], show_cols: List[str]) -> None:
    # Compute column widths
    widths = {c: len(c) for c in show_cols}
    for _, rows in groups.items():
        for r in rows:
            for c in show_cols:
                s = str(r.get(c, ""))
                if len(s) > widths[c]:
                    widths[c] = len(s)
    header = "  ".join(c.ljust(widths[c]) for c in show_cols)
    sep = "  ".join("-" * widths[c] for c in show_cols)
    first = True
    for fname, rows in groups.items():
        if not rows:
            continue
        if first:
            print(header)
            print(sep)
            first = False
        for r in rows:
            print("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in show_cols))


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze benchmark CSV results and extract top argument combinations per file.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(subp: argparse.ArgumentParser) -> None:
        subp.add_argument("--csv", action="append", type=Path, required=False,
                          help="Path(s) to CSV files. If omitted, defaults to the chosen algo's csv.path under scripts/benchmarks/out.")
        subp.add_argument("--algo", required=True,
                          help="Algorithm name (from scripts/benchmarks/configs/algorithms.json). Required; no inference from file names or headers.")
        subp.add_argument("--filter", action="append", default=[],
                          help="Filter rows by key=value (comma-separated values allowed). Repeatable.")
        subp.add_argument("--param-cols", default=None,
                          help="Comma-separated list of parameter columns to define a unique argument combination. Defaults per algorithm.")
        subp.add_argument("--show", default=None,
                          help="Comma-separated list of columns to display. Defaults to [file, modularity] + param cols.")
        subp.add_argument("--format", choices=["table", "json", "csv"], default="table",
                          help="Output format.")

    top = sub.add_parser("top", help="Show top-N per file by a metric (default: modularity if present, else total_sec)")
    add_common(top)
    top.add_argument("--top", type=int, default=5, help="Top N per file")
    top.add_argument("--sort-key", default=None, help="Metric to sort by (default: modularity if present, else total_sec)")
    top.add_argument("--asc", action="store_true", help="Sort ascending instead of descending (defaults to desc for modularity; asc for time)")
    top.add_argument("--no-dedup", action="store_true", help="Do not deduplicate by parameter combination")

    args = ap.parse_args()

    # Load algorithms config
    config_path = Path(__file__).resolve().parent.parent / "configs" / "algorithms.json"
    algos = load_algorithms_config(config_path)

    # Validate algorithm and choose default CSV path from its config if needed
    if args.algo not in algos:
        print(f"Unknown --algo '{args.algo}'. Available: {', '.join(sorted(algos.keys()))}")
        return
    csv_paths = args.csv
    if not csv_paths:
        csv_file_name = algos[args.algo].get("csv", {}).get("path", "results.csv")
        default = Path(__file__).resolve().parent.parent / "out" / csv_file_name
        csv_paths = [default]

    try:
        rows = load_csv(csv_paths)
    except FileNotFoundError as exc:
        print(exc)
        return
    if not rows:
        print("No rows found. Check CSV path(s).")
        return
    # Use explicitly provided algorithm and coerce numeric types using its param hints
    algo = args.algo
    all_cols = list(rows[0].keys())
    algo_entry = algos.get(algo, {})
    numeric_hint: Set[str] = set()
    for p in algo_entry.get("params", []):
        name = p.get("name")
        ptype = p.get("type")
        if name and ptype in {"int", "float"}:
            numeric_hint.add(name)
    # Also add common timing columns that appear in the sheet
    for c in ["total_sec", "parse_sec", "vig_build_sec", "seg_sec","agg_memory"]:
        if c in all_cols:
            numeric_hint.add(c)
    coerce_types(rows, numeric_hint=numeric_hint)
    # refresh columns after coercion
    all_cols = list(rows[0].keys())
    user_param_cols = [c.strip() for c in args.param_cols.split(",") if c.strip()] if args.param_cols else None
    param_cols = param_columns_for_algo(algo_entry, all_cols, user_param_cols)

    rows = apply_filters(rows, args.filter)

    if not rows:
        print("No rows remain after applying filters.")
        return

    if args.cmd == "top":
        top_n = int(args.top)
        # Determine sort key and default order
        if args.sort_key:
            sort_key = str(args.sort_key)
            descending = not bool(args.asc)
        else:
            if "modularity" in all_cols:
                sort_key = "modularity"
                descending = True
            elif "total_sec" in all_cols:
                sort_key = "total_sec"
                descending = False
            elif "seg_sec" in all_cols:
                sort_key = "seg_sec"
                descending = False
            elif "vig_build_sec" in all_cols:
                sort_key = "vig_build_sec"
                descending = False
            else:
                # fallback: first numeric-looking column
                numeric_candidates = [c for c in all_cols if isinstance(rows[0].get(c), (int, float))]
                sort_key = numeric_candidates[0] if numeric_candidates else all_cols[0]
                descending = True
        groups = top_per_file(rows, top_n, param_cols, sort_key, descending, dedup_params=not args.no_dedup)

        # Decide columns to show
        if args.show:
            show_cols = [c.strip() for c in args.show.split(",") if c.strip()]
        else:
            # Choose identifier column: prefer 'file', else 'file_id'
            id_col = "file" if "file" in all_cols else ("file_id" if "file_id" in all_cols else "file")
            base = [id_col, sort_key]
            # include a compact subset of params by default
            # Ensure uniqueness and preserve order
            seen = set()
            ordered_params = []
            for c in param_cols:
                if c not in seen:
                    seen.add(c)
                    ordered_params.append(c)
            show_cols = base + ordered_params
            # Keep only those present
            show_cols = [c for c in show_cols if c in all_cols or c == sort_key or c in {"file", "file_id"}]

        if args.format == "table":
            print_table(groups, show_cols)
        elif args.format == "json":
            # emit list of records with only show_cols
            out = []
            for _, rows_ in groups.items():
                for r in rows_:
                    out.append({c: r.get(c) for c in show_cols})
            print(json.dumps(out, indent=2))
        else:  # csv
            writer = csv.writer(sys.stdout)
            writer.writerow(show_cols)
            for _, rows_ in groups.items():
                for r in rows_:
                    writer.writerow([r.get(c, "") for c in show_cols])


if __name__ == "__main__":
    main()
