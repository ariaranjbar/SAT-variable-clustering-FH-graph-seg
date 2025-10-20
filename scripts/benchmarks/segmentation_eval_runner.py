#!/usr/bin/env python3
"""
segmentation_eval_runner.py

A simple, specialized runner for the segmentation_eval binary.
- Reads a JSON config describing inputs and sweep parameters.
- Samples a number of random CNF files from a root folder (supports .cnf and .cnf.xz).
- Runs segmentation_eval once per sampled file, writing a per-file CSV.
- Produces a combined CSV at the end (adds a 'file_id' column and maintains file_map.csv).

JSON config example:
{
  "root_dir": "benchmarks",
  "sample_count": 20,
  "recursive": true,
  "out_dir": "scripts/benchmarks/out/seg_eval",
  "combined_csv": "scripts/benchmarks/out/seg_eval/combined.csv",
  "bin": "build/algorithms/segmentation_eval/segmentation_eval",
  "impl": "opt",            # or "naive"
  "threads": 0,             # 0 = auto
  "maxbuf": 50000000,
  "tau": "inf",
  "k": "10,30,100",
  "size_exp": "1.0,1.95",
  "mod_guard": "on,off",
  "gamma": "1.0,0.5",
  "anneal": "on,off",
  "dq_tol0": "5e-4,1e-3",
  "dq_vscale": "0,10",
  "ambiguous": "accept,reject,margin",
  "gate_margin": "0.01,0.05",
  "seed": 123                # optional: for reproducible sampling
}

Usage:
  python scripts/benchmarks/segmentation_eval_runner.py path/to/config.json
"""
from __future__ import annotations

import argparse
import csv
import json
import lzma
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def find_inputs(root: Path, recursive: bool) -> List[Path]:
    patterns = ["*.cnf", "*.cnf.xz"]
    files: List[Path] = []
    if recursive:
        for pat in patterns:
            files.extend(root.rglob(pat))
    else:
        for pat in patterns:
            files.extend(root.glob(pat))
    return [p for p in files if p.is_file()]


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def run_seg_eval_on_file(bin_path: Path, cnf_path: Path, out_csv: Path, cfg: dict) -> int:
    """Run segmentation_eval on a single file. Handles .xz by decompressing to a temp file.
    Returns the process return code.
    """
    input_path = cnf_path
    temp_path: Optional[Path] = None

    if cnf_path.suffix == ".xz":
        # Decompress to a temporary file to avoid depending on stdin semantics.
        try:
            with lzma.open(cnf_path, "rb") as f_in:
                # Infer base name without .xz
                base = cnf_path.with_suffix("").name
                if not base.endswith(".cnf"):
                    base += ".cnf"
                fd, tmp_name = tempfile.mkstemp(prefix="seg_eval_", suffix="_" + base)
                os.close(fd)
                with open(tmp_name, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
                temp_path = Path(tmp_name)
                input_path = temp_path
        except Exception as e:
            print(f"[error] failed to decompress {cnf_path}: {e}", file=sys.stderr)
            return 1

    ensure_dir(out_csv.parent)
    args = [str(bin_path), "-i", str(input_path), "--out-csv", str(out_csv)]

    # Builder controls
    impl = str(cfg.get("impl", "opt")).lower()
    if impl == "naive":
        args.append("--naive")
    else:
        args.append("--opt")
        if "threads" in cfg:
            args += ["-t", str(int(cfg["threads"]))]
        if "maxbuf" in cfg:
            args += ["--maxbuf", str(int(cfg["maxbuf"]))]

    # VIG tau
    if "tau" in cfg:
        args += ["--tau", str(cfg["tau"])]

    # Sweep knobs: pass through strings as provided
    def maybe(opt_name_json: str, cli_opt: str) -> None:
        val = cfg.get(opt_name_json)
        if val is not None and str(val) != "":
            args.extend([cli_opt, str(val)])

    maybe("k", "-k")
    maybe("size_exp", "--size-exp")
    maybe("mod_guard", "--mod-guard")
    maybe("gamma", "--gamma")
    maybe("anneal", "--anneal")
    maybe("dq_tol0", "--dq-tol0")
    maybe("dq_vscale", "--dq-vscale")
    maybe("ambiguous", "--ambiguous")
    maybe("gate_margin", "--gate-margin")

    # Print a compact status line
    print(f"[run] {cnf_path} -> {out_csv}")
    sys.stdout.flush()

    timing_pattern = re.compile(
        r"segmentation_eval:\s*parse_sec=([0-9eE+\-.]+)\s+build_inf_sec=([0-9eE+\-.]+)\s+build_user_sec=([0-9eE+\-.]+)"
    )
    parse_t = build_inf_t = build_user_t = None

    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            # forward child output
            sys.stdout.write(line)
            # try to parse timing line
            m = timing_pattern.search(line)
            if m:
                try:
                    parse_t = float(m.group(1))
                    build_inf_t = float(m.group(2))
                    build_user_t = float(m.group(3))
                except Exception:
                    pass
        rc = proc.wait()
        if rc == 0 and parse_t is not None and build_inf_t is not None and build_user_t is not None:
            print(f"[timings] parse={parse_t:.6f}s build_inf={build_inf_t:.6f}s build_user={build_user_t:.6f}s")
        return rc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except Exception:
                pass


def load_file_map(map_path: Path) -> Tuple[Dict[str, int], int]:
    """Load an existing file map (file_id,file_path). Returns (path_to_id, next_id)."""
    mapping: Dict[str, int] = {}
    next_id = 0
    if map_path.exists():
        try:
            with map_path.open("r", newline="") as f:
                r = csv.reader(f)
                _header = next(r, None)
                for row in r:
                    if len(row) < 2:
                        continue
                    fid = int(row[0])
                    fpath = row[1]
                    mapping[fpath] = fid
                    next_id = max(next_id, fid + 1)
        except Exception as e:
            print(f"[warn] could not read existing file map {map_path}: {e}", file=sys.stderr)
    return mapping, next_id


def write_file_map(map_path: Path, mapping: Dict[str, int]) -> None:
    ensure_dir(map_path.parent)
    # invert to id->path for stable ordering
    inv: Dict[int, str] = {v: k for k, v in mapping.items()}
    with map_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_id", "file_path"])
        for fid in sorted(inv.keys()):
            w.writerow([fid, inv[fid]])


def migrate_combined_to_per_header(
    combined_csv: Path, map_path: Path, per_header: List[str]
) -> Tuple[Dict[str, int], int]:
    """Ensure combined.csv matches the target header (per_header + 'file_id').
    Handles legacy combined with trailing 'file' or with extra/older columns by selecting columns by name.
    Returns (mapping, next_id) after any migration, where mapping is the file_path->id map
    loaded (and possibly extended) from file_map.csv.
    """
    mapping, next_id = load_file_map(map_path)
    target_header = list(per_header) + ["file_id"]
    if not combined_csv.exists():
        return mapping, next_id

    try:
        with combined_csv.open("r", newline="") as f:
            r = csv.reader(f)
            old_header = next(r, None)
            if not old_header:
                return mapping, next_id
            if old_header == target_header:
                return mapping, next_id

            # Determine file id source
            if old_header[-1] == "file":
                file_col_is_path = True
                id_col_idx = None
            elif old_header[-1] == "file_id":
                file_col_is_path = False
                id_col_idx = len(old_header) - 1
            else:
                # Unknown schema; do not migrate
                return mapping, next_id

            # Build index mapping for per_header names
            name_to_idx = {name: i for i, name in enumerate(old_header)}
            select_indices: List[int] = []
            for name in per_header:
                if name not in name_to_idx:
                    # Can't migrate; missing column
                    return mapping, next_id
                select_indices.append(name_to_idx[name])

            # Read rows and rebuild into target schema
            new_rows: List[List[str]] = []
            for row in r:
                if not row:
                    continue
                values = [row[i] for i in select_indices]
                if file_col_is_path:
                    file_path = row[-1]
                    if file_path not in mapping:
                        mapping[file_path] = next_id
                        next_id += 1
                    fid = mapping[file_path]
                else:
                    try:
                        fid = int(row[id_col_idx])  # type: ignore[arg-type]
                    except Exception:
                        # If not an int, skip
                        continue
                new_rows.append(values + [str(fid)])

        # Write migrated combined
        with combined_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(target_header)
            for row in new_rows:
                w.writerow(row)

        # Persist file map
        write_file_map(map_path, mapping)
        print("[migrate] adjusted combined.csv header and file mapping to target schema")
        return mapping, next_id
    except Exception as e:
        print(f"[warn] failed to migrate combined.csv: {e}", file=sys.stderr)
        return mapping, next_id


def append_per_file_to_combined(
    per_file_csv: Path,
    orig_cnf: Path,
    combined_csv: Path,
    map_path: Path,
    mapping: Dict[str, int],
    next_id: int,
) -> Tuple[bool, int]:
    """Append a per-file CSV into combined.csv with a numeric file_id, delete per-file CSV on success.
    Maintains and writes file_map.csv later (mapping persisted by caller).
    Returns (ok, updated_next_id).
    """
    try:
        with per_file_csv.open("r", newline="") as f:
            reader = csv.reader(f)
            per_header = next(reader, None)
            if per_header is None:
                print(f"[warn] empty CSV: {per_file_csv}", file=sys.stderr)
                return False, next_id

            ensure_dir(combined_csv.parent)

            # Ensure combined is migrated to match this per-file header
            migrated_map, migrated_next = migrate_combined_to_per_header(combined_csv, map_path, list(per_header))
            # Merge any newly discovered mappings
            for k, v in migrated_map.items():
                if k not in mapping:
                    mapping[k] = v
            next_id = max(next_id, migrated_next)

            if not combined_csv.exists() or combined_csv.stat().st_size == 0:
                with combined_csv.open("w", newline="") as out_f:
                    writer = csv.writer(out_f)
                    writer.writerow(list(per_header) + ["file_id"])
            else:
                # Validate header compatibility and that last col is file_id
                with combined_csv.open("r", newline="") as cf:
                    cr = csv.reader(cf)
                    comb_header = next(cr, None)
                if comb_header is None or list(comb_header)[:-1] != list(per_header) or comb_header[-1] != "file_id":
                    print(f"[warn] header mismatch for {per_file_csv}; expected last column 'file_id'", file=sys.stderr)
                    return False, next_id

            # Resolve file id (use resolved absolute path for stability)
            key = str(orig_cnf.resolve())
            if key in mapping:
                fid = mapping[key]
            else:
                fid = next_id
                mapping[key] = fid
                next_id += 1

            with combined_csv.open("a", newline="") as out_f:
                writer = csv.writer(out_f)
                for row in reader:
                    writer.writerow(row + [fid])

        # Persist the updated file map after each successful append
        try:
            write_file_map(map_path, mapping)
        except Exception as e:
            print(f"[warn] failed to update file map {map_path}: {e}", file=sys.stderr)

        # delete per-file CSV after successful append
        try:
            per_file_csv.unlink()
        except Exception:
            pass

        print(f"[merge] appended {per_file_csv.name} -> {combined_csv}")
        return True, next_id

    except FileNotFoundError:
        print(f"[warn] missing CSV: {per_file_csv}", file=sys.stderr)
        return False, next_id
    except Exception as e:
        print(f"[warn] failed to append {per_file_csv}: {e}", file=sys.stderr)
        return False, next_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Run segmentation_eval over a random sample of CNFs")
    ap.add_argument("config", help="Path to JSON config")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    with cfg_path.open("r") as f:
        cfg = json.load(f)

    # Optional reproducible sampling
    if "seed" in cfg:
        try:
            random.seed(int(cfg["seed"]))
        except Exception:
            pass

    root = Path(cfg.get("root_dir", "benchmarks")).resolve()
    if not root.exists():
        print(f"[error] root_dir not found: {root}", file=sys.stderr)
        return 2

    recursive = bool(cfg.get("recursive", True))
    sample_count = int(cfg.get("sample_count", 10))

    bin_path = Path(cfg.get("bin", "build/algorithms/segmentation_eval/segmentation_eval")).resolve()
    if not bin_path.exists():
        print(f"[error] binary not found: {bin_path}", file=sys.stderr)
        return 2

    out_dir = Path(cfg.get("out_dir", "scripts/benchmarks/out/seg_eval")).resolve()
    ensure_dir(out_dir)
    combined_csv = Path(cfg.get("combined_csv", str(out_dir / "combined.csv"))).resolve()
    file_map_csv = (combined_csv.parent if combined_csv.parent else out_dir) / "file_map.csv"

    # Load existing mapping; combined migration happens per-append using per-file header
    file_map, next_id = load_file_map(file_map_csv)

    # Find and sample inputs
    all_inputs = find_inputs(root, recursive)
    if not all_inputs:
        print(f"[error] no inputs found under {root}", file=sys.stderr)
        return 2
    random.shuffle(all_inputs)
    chosen = all_inputs[: min(sample_count, len(all_inputs))]
    print(f"[info] sampled {len(chosen)} / {len(all_inputs)} inputs from {root}")

    failures = 0
    for i, cnf in enumerate(chosen, 1):
        # Build per-file CSV name, stripping .cnf and .xz if present
        stem = cnf.stem
        if stem.endswith(".cnf"):
            stem = Path(stem).stem
        out_csv = out_dir / f"{stem}__seg_eval.csv"

        rc = run_seg_eval_on_file(bin_path, cnf, out_csv, cfg)
        if rc != 0:
            print(f"[fail] ({rc}) {cnf}", file=sys.stderr)
            failures += 1
        else:
            ok, next_id = append_per_file_to_combined(out_csv, cnf, combined_csv, file_map_csv, file_map, next_id)
            if not ok:
                failures += 1

        if i % 5 == 0:
            print(f"[progress] {i}/{len(chosen)} done")

    # Write/refresh file_map.csv
    write_file_map(file_map_csv, file_map)

    if failures:
        print(f"[done] completed with {failures} failures")
    else:
        print(f"[done] all runs succeeded -> {combined_csv} (map: {file_map_csv})")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
