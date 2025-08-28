#!/usr/bin/env python
import argparse
import csv
import os
import platform
import random
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import hashlib
import json

# Notes
# - Mirrors the behavior of run_vig_info_random.sh and run_segmentation_random.sh
# - Writes CSVs to scripts/benchmarks/out with identical headers and row shapes
# - Keeps logs only on failure or when summary parsing fails
# - Supports: --reuse-files / --from-csv, --skip-existing, --cache/--no-cache, --memlimits, --dry-run, --verbose
# - Decompression: streams with xz -dc by default; optional caching to a temp file per file

ROOT_DIR = Path(__file__).resolve().parents[2]
BENCH_DIR_DEFAULT = ROOT_DIR / "benchmarks"
OUT_DIR_DEFAULT = ROOT_DIR / "scripts/benchmarks/out"

# (CSV schemas and required keys now come from the registry/config; no hardcoded schemas here)

# ---------------- Config-driven mode types ----------------

# Lightweight schema support using JSON (and optional YAML if installed).

class ConfigError(Exception):
    pass

# -------------- Utility helpers --------------

def vprint(enabled: bool, *args) -> None:
    if enabled:
        print("[info]", *args, file=sys.stderr)


def ensure_out_dir(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)


# (binary discovery is handled via _discover_bin_by_name and registry-provided lists)


def list_bench_files(bench_dir: Path) -> List[Path]:
    pats = ("*.cnf", "*.cnf.xz")
    files: List[Path] = []
    for root, _dirs, _files in os.walk(bench_dir):
        for p in pats:
            for f in Path(root).glob(p):
                files.append(f)
    files.sort()
    return files


def select_files(all_files: List[Path], n: int, reuse_csv: Optional[Path], bench_dir: Path, verbose: bool) -> List[Path]:
    if reuse_csv is not None:
        if not reuse_csv.is_file():
            raise FileNotFoundError(f"Reuse CSV not found: {reuse_csv}")
        bases: List[str] = []
        with reuse_csv.open() as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if not row: continue
                bases.append(row[0])
        uniq = sorted(set(bases))
        sel: List[Path] = []
        for bn in uniq:
            found = None
            for p in all_files:
                if p.name == bn:
                    found = p
                    break
            if found:
                sel.append(found)
            else:
                vprint(verbose, f"[warn] Not found in benchmarks/: {bn}")
        vprint(verbose, f"Reusing {len(sel)} files from CSV: {reuse_csv} (ignoring -n)")
        return sel
    # random pick N
    shuf = list(all_files)
    random.shuffle(shuf)
    sel = shuf[:n]
    vprint(verbose, f"Selected {len(sel)} random files (requested -n {n})")
    return sel


# (tau-specific normalization removed; rely on generic schema constraints such as allow_inf, numeric, min/max)


def build_keys_set(csv_path: Path, key_cols: List[int]) -> Optional[set]:
    if not csv_path.exists():
        return None
    keys = set()
    with csv_path.open() as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if not row: continue
            key = ",".join(row[i] for i in key_cols)
            keys.add(key)
    return keys


def parse_summary_lines(lines: Iterable[str]) -> Dict[str, str]:
    # Parse lines into dicts of key=value; return the last one containing required keys
    last_map: Dict[str, str] = {}
    for ln in lines:
        pairs = re.findall(r"(\w+)=([^\s]+)", ln)
        if not pairs:
            continue
        m = {k: v for (k, v) in pairs}
        last_map = m
    return last_map


def csv_append(csv_path: Path, header: List[str], row: List[str]) -> None:
    new_file = not csv_path.exists()
    with csv_path.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerow(row)


def os_is_darwin() -> bool:
    return platform.system() == "Darwin"


# -------------- Execution helpers --------------

def run_with_streaming(cmd: List[str], infile: Path, log_path: Path, verbose: bool,
                       memlimit_mb: Optional[int] = None,
                       log_header: Optional[str] = None) -> Tuple[int, List[str]]:
    """Run `cmd` with stdin as xz -dc of infile (if .xz) or direct file via -i path,
    capturing stdout to log and memory-limiting on Linux. Return (exit_code, output_lines)."""
    ensure_out_dir(log_path.parent)

    # Prepare stdin source
    xz_proc = None
    stdin_src = None

    def set_memlimit():
        if memlimit_mb is None:
            return
        if os_is_darwin():
            # parity with bash: warn once; ignore limit
            pass
        else:
            try:
                import resource
                # RLIMIT_AS expects bytes on Linux
                b = memlimit_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (b, b))
            except Exception as e:
                print(f"[warn] Failed to set memlimit: {e}", file=sys.stderr)

    try:
        if infile.suffix == ".xz":
            # stream via xz -dc
            xz_cmd = ["xz", "-dc", "--", str(infile)]
            if verbose:
                vprint(True, "PIPE:", " ".join(shlex.quote(x) for x in xz_cmd), "|", " ".join(shlex.quote(x) for x in cmd))
            xz_proc = subprocess.Popen(xz_cmd, stdout=subprocess.PIPE)
            stdin_src = xz_proc.stdout
            # cmd expects -i - already present in cmd list
            proc = subprocess.Popen(cmd, stdin=stdin_src, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, preexec_fn=set_memlimit if not os_is_darwin() else None)
        else:
            if verbose:
                vprint(True, "RUN:", " ".join(shlex.quote(x) for x in cmd))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, preexec_fn=set_memlimit if not os_is_darwin() else None)

        lines: List[str] = []
        with log_path.open("w") as logf:
            if log_header:
                logf.write(log_header)
                if not log_header.endswith("\n"):
                    logf.write("\n")
                logf.flush()
            assert proc.stdout is not None
            for ln in proc.stdout:
                logf.write(ln)
                logf.flush()
                lines.append(ln.rstrip("\n"))
                if verbose:
                    # emulate tee to console under -v
                    sys.stderr.write(ln)
        rc = proc.wait()
        if xz_proc is not None:
            try:
                xz_proc.terminate()
            except Exception:
                pass
        return rc, lines
    finally:
        if xz_proc is not None and xz_proc.stdout is not None:
            try:
                xz_proc.stdout.close()
            except Exception:
                pass


# -------------- Generic config runner helpers --------------

def _load_config(path: Path) -> dict:
    try:
        import json
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except Exception as e:
                raise ConfigError("YAML config requested but PyYAML not installed. Install pyyaml or use JSON.") from e
            with path.open() as f:
                return yaml.safe_load(f)
        else:
            with path.open() as f:
                return json.load(f)
    except ConfigError:
        raise
    except Exception as e:
        raise ConfigError(f"Failed to parse config {path}: {e}")


def _discover_bin_generic(target_name: str, roots: List[Path]) -> Optional[Path]:
    """Search recursively under roots for an executable file named target_name.
    Returns the first match found."""
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _dirs, files in os.walk(root):
            if target_name in files:
                cand = Path(dirpath) / target_name
                if cand.is_file() and os.access(cand, os.X_OK):
                    return cand
    return None


def _discover_bin_by_name(name: str) -> Optional[Path]:
    """Discover a binary by algorithm name without hardcoded paths.
    - Prefer registry-provided discover entries if available.
    - Fallback: recursively search under build/ for an executable named <name>.
    """
    # Try algorithms registry
    try:
        reg = _load_algorithms_registry()
        cfg = reg.get(name)
        if cfg:
            for c in (cfg.get("discover") or []):
                cand = (ROOT_DIR / c)
                if cand.is_file() and os.access(cand, os.X_OK):
                    return cand
    except Exception:
        pass
    # Generic search under build/
    return _discover_bin_generic(name, [ROOT_DIR / "build"])


def _eval_condition(cond: dict, params: Dict[str, str]) -> bool:
    """Evaluate simple condition objects on current params.
    Supported:
    - {"equals": {"key": "impl", "value": "opt"}}
    - {"in": {"key": "impl", "values": ["opt","naive"]}}
    - {"and": [ ... ]}
    - {"or": [ ... ]}
    - {"not": { ... }}
    """
    if not cond:
        return True
    if "equals" in cond:
        obj = cond["equals"] or {}
        key = obj.get("key"); val = obj.get("value")
        return str(params.get(key, "")) == str(val)
    if "in" in cond:
        obj = cond["in"] or {}
        key = obj.get("key"); vals = obj.get("values", [])
        return str(params.get(key, "")) in [str(v) for v in vals]
    if "and" in cond:
        arr = cond.get("and") or []
        return all(_eval_condition(c, params) for c in arr)
    if "or" in cond:
        arr = cond.get("or") or []
        return any(_eval_condition(c, params) for c in arr)
    if "not" in cond:
        return not _eval_condition(cond.get("not") or {}, params)
    # unknown condition => false for safety
    return False


def _expand_values(spec: dict, key: str) -> List[str]:
    """Expand a value spec to a list of string values.
    Supported forms:
    - scalar: 42, "inf"
    - list: [1,2,3]
    - range: {"range": {"start": 1, "stop": 5, "step": 2}}  => 1,3
    """
    if key not in spec:
        return []
    v = spec[key]
    if isinstance(v, dict) and "range" in v:
        r = v["range"]
        start = r.get("start")
        stop = r.get("stop")
        step = r.get("step", 1)
        if start is None or stop is None:
            raise ConfigError(f"range for {key} requires start and stop")
        vals = list(range(int(start), int(stop), int(step)))
        return [str(x) for x in vals]
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


# (legacy per-param normalizers removed; validation happens when building param specs)


def _product_sweep(param_specs: List[dict], base_params: Dict[str, str]) -> List[Dict[str, str]]:
    """Generate a list of parameter dicts by applying each param spec with conditions.
    param_specs example entries:
      {"name":"impl", "values":["naive","opt"]}
      {"name":"threads", "values":[1,2,4], "when":{"equals":{"key":"impl","value":"opt"}}}
    """
    # Start with base
    combos = [dict(base_params)]
    for spec in param_specs:
        name = spec.get("name")
        if not name:
            raise ConfigError("Each parameter spec requires a 'name'")
        values = _expand_values(spec, "values")
        cond = spec.get("when")
        new_combos: List[Dict[str, str]] = []
        for c in combos:
            # Decide if we sweep this param (condition based on current c)
            if cond is None or _eval_condition(cond, c):
                for v in values or [c.get(name)]:
                    if v is None:
                        continue
                    nc = dict(c)
                    nc[name] = str(v)
                    new_combos.append(nc)
            else:
                # Keep as is; param not applied for this combo
                new_combos.append(dict(c))
        combos = new_combos
    # All param values already validated; return combos as-is
    return combos


def _format_cmd(cmd_template: List[str], params: Dict[str, str], infile: Path, bin_path: Optional[Path] = None) -> List[str]:
    # Replace ${key} occurrences with params[key]; special token ${input} becomes '-' or file path
    # If template references ${bin}, ensure it's resolved
    p = dict(params)
    if any("${bin}" in t for t in cmd_template):
        # Auto-fill when missing or explicit auto
        if ("bin" not in p) or (str(p.get("bin")) in ("${auto}", "auto")):
            if bin_path is None:
                raise ConfigError("cmd_template uses ${bin} but no binary path was provided or discovered")
            p["bin"] = str(bin_path)
    tokens = [tok.replace("${input}", "-" if infile.suffix == ".xz" else str(infile)) for tok in cmd_template]
    for k, v in p.items():
        tokens = [t.replace(f"${{{k}}}", str(v)) for t in tokens]
    # Drop unresolved placeholder pairs like ['-t','${threads}'] or ['--maxbuf','${maxbuf}']
    cleaned: List[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if i + 1 < len(tokens) and tokens[i+1].startswith("${") and tokens[i+1].endswith("}") and t.startswith("-"):
            # skip both flag and unresolved value
            i += 2
            continue
        # also skip any standalone unresolved placeholders
        if t.startswith("${") and t.endswith("}"):
            i += 1
            continue
        cleaned.append(t)
        i += 1
    tokens = cleaned
    # Remove any empty tokens (useful for optional flags that may expand to "")
    tokens = [t for t in tokens if t != ""]
    # If template already included ${bin}, it's now resolved in tokens. Otherwise prepend bin_path if provided.
    if any(t == "${bin}" for t in tokens):
        # unresolved bin is an error
        raise ConfigError("Unresolved ${bin} in cmd_template")
    if any("${bin}" in t for t in cmd_template):
        return tokens
    if bin_path is not None:
        return [str(bin_path)] + tokens
    return tokens


def _subst_template(tmpl: str, vars_map: Dict[str, str]) -> str:
    s = str(tmpl)
    for k, v in vars_map.items():
        s = s.replace(f"${{{k}}}", str(v))
    return s


def _compute_auto_params(algo_cfg: dict, combo: Dict[str, str], out_dir: Path, algo_name: str, file_path: Optional[Path]) -> Dict[str, str]:
    """Compute algorithm-specific auto-generated parameters.
    Schema per entry:
        {"name": "param_name", "template": "relative/or/absolute/with/${vars}", "join_out_dir": true|false, "when": { ... }}
    - Supports optional 'when' conditions (same structure as params 'when'). If present and false, this auto param is skipped.
    Vars available to template/conditions: all keys in combo, plus algo, out_dir, file, file_stem, file_root.
    When join_out_dir is true, final path = out_dir / substituted(template).
    """
    res: Dict[str, str] = {}
    auto_list = algo_cfg.get("auto_params", []) or []
    if not isinstance(auto_list, list):
        return res
    for ap in auto_list:
        if not isinstance(ap, dict):
            continue
        name = ap.get("name")
        tmpl = ap.get("template") or ap.get("path_template")
        if not name or not tmpl:
            continue
        vars_map: Dict[str, str] = {}
        vars_map.update(combo)
        # Derive file_root (strip all suffixes) for original file
        file_root = ""
        if file_path is not None:
            p = file_path.name
            # emulate Path.stem repeatedly
            base = Path(p)
            while True:
                s = base.suffix
                if not s:
                    break
                base = Path(base.stem)
            file_root = base.name

        vars_map.update({
            "algo": str(algo_name),
            "out_dir": str(out_dir),
            "file": "" if file_path is None else file_path.name,
            "file_stem": "" if file_path is None else file_path.stem,
            "file_root": file_root,
        })
        # Optional condition to include this auto param
        cond = ap.get("when")
        if cond is not None and not _eval_condition(cond, vars_map):
            # Skip generating this auto param when condition is false
            continue

        val = _subst_template(str(tmpl), vars_map)
        if bool(ap.get("join_out_dir", False)):
            val = str(out_dir / val)
        res[name] = val
    return res


def _slug_value(val: str, max_len: int = 80) -> str:
    """Make a value safe for filenames: replace path separators and other unsafe chars.
    Also clamp length to avoid overlong filenames.
    """
    s = str(val)
    # Replace any non-alnum and not in a small safe set with '_'
    s = re.sub(r"[^A-Za-z0-9._+-]", "_", s)
    if len(s) > max_len:
        s = s[:max_len]
    return s


def _params_tag(params: Dict[str, str], exclude_keys: Optional[List[str]] = None) -> str:
    """Build a compact, filesystem-safe tag from params for log filenames.
    exclude_keys: parameter names to skip (e.g., long path-like values).
    """
    exclude = set(exclude_keys or [])
    parts: List[str] = []
    for k in sorted(params.keys()):
        if k in exclude:
            continue
        v = params[k]
        parts.append(f"{k}{_slug_value(v)}")
    return ".".join(parts)


def _short_hash_tag(params: Dict[str, str], extra: Optional[Dict[str, str]] = None, length: int = 12) -> str:
    """Build a short, stable hash tag from params and optional extras.
    Uses SHA1 over a JSON dump with sorted keys, then returns first `length` hex chars.
    """
    m: Dict[str, str] = dict(params)
    if extra:
        m.update({k: str(v) for k, v in extra.items()})
    blob = json.dumps(m, sort_keys=True, separators=(",", ":")).encode("utf-8")
    h = hashlib.sha1(blob).hexdigest()
    return h[:max(8, min(40, length))]


def _parse_required_keys(lines: List[str], required: List[str]) -> Optional[Dict[str, str]]:
    m = parse_summary_lines(lines)
    return m if all(k in m for k in required) else None


def run_from_config(config_path: Path, verbose: bool = False) -> int:
    cfg = _load_config(config_path)
    # Top-level settings
    out_dir = Path(cfg.get("out_dir", OUT_DIR_DEFAULT))
    bench_dir = Path(cfg.get("bench_dir", BENCH_DIR_DEFAULT))
    ensure_out_dir(out_dir)

    # Files selection
    files_spec = cfg.get("files", {}) or {}
    reuse_csv = files_spec.get("reuse_csv")
    reuse_csv_path = Path(reuse_csv) if reuse_csv else None
    count = int(files_spec.get("count", 0))

    # List all benchmark files
    all_files = list_bench_files(bench_dir)
    if not all_files:
        print(f"No benchmark files found in {bench_dir}", file=sys.stderr)
        return 4

    # Select files
    if reuse_csv_path is not None:
        sel_files = select_files(all_files, 0, reuse_csv_path, bench_dir, verbose)
    else:
        if count <= 0:
            raise ConfigError("files.count must be > 0 when reuse_csv not provided")
        sel_files = select_files(all_files, count, None, bench_dir, verbose)

    # Load registry for defaults/schema
    try:
        registry = _load_algorithms_registry()
    except Exception:
        registry = {}

    # Iterate algorithms
    algos = cfg.get("algorithms", [])
    if not isinstance(algos, list) or not algos:
        raise ConfigError("'algorithms' must be a non-empty list")

    for algo in algos:
        name = algo.get("name")
        if not name:
            raise ConfigError("Each algorithm requires a name")
        reg_algo = registry.get(name, {})

        # Resolve binary
        bin_path: Optional[Path] = None
        bin_val = algo.get("bin")
        if bin_val:
            bin_path = Path(bin_val)
            if not (bin_path.is_file() and os.access(bin_path, os.X_OK)):
                raise ConfigError(f"Binary not executable: {bin_path}")
        else:
            # Try discover from config, then registry, then generic by name
            disc_list = (algo.get("discover") or []) or (reg_algo.get("discover") or [])
            if disc_list:
                for c in disc_list:
                    cand = ROOT_DIR / c
                    if cand.is_file() and os.access(cand, os.X_OK):
                        bin_path = cand
                        break
            if not bin_path:
                b = _discover_bin_by_name(name)
                if not b:
                    raise ConfigError(f"Could not auto-discover binary for {name}; provide 'bin' or define discover in registry/config")
                bin_path = b

        # Command template and CSV schema from config or registry
        cmd_template = algo.get("cmd_template") or reg_algo.get("cmd_template")
        if not isinstance(cmd_template, list) or not cmd_template:
            raise ConfigError("cmd_template must be provided in config or registry")
        csv_obj = (algo.get("csv") or {}) or (reg_algo.get("csv") or {})
        csv_name = csv_obj.get("path") or f"{name}_results.csv"
        csv_path = out_dir / csv_name
        header = csv_obj.get("header")
        required_keys = csv_obj.get("required_keys")
        if not header or not required_keys:
            raise ConfigError("csv.header and csv.required_keys must be provided (via config or registry)")

        # Keys for skip-existing
        skip_existing = bool(algo.get("skip_existing", False))
        if skip_existing:
            key_cols = csv_obj.get("key_cols")
            if not isinstance(key_cols, list):
                raise ConfigError("csv.key_cols must be provided when skip_existing is true")
            keys = build_keys_set(csv_path, key_cols)
        else:
            keys = None

        # Per-file caching and memlimit
        cache = bool(algo.get("cache", True))
        memlimits = algo.get("memlimits", []) or []

        # Base params: registry defaults overridden by config
        base_params_src = {}
        base_params_src.update(reg_algo.get("base_params") or {})
        base_params_src.update(algo.get("base_params") or {})
        base_params: Dict[str, str] = {k: str(v) for k, v in base_params_src.items()}

        # Parameters: allow simplified mapping overrides or legacy list format
        overrides = algo.get("parameters") or {}
        reg_params: List[dict] = reg_algo.get("params", []) or []
        param_specs: List[dict] = []
        if isinstance(overrides, dict):
            # overrides is mapping name -> list of values
            for p in reg_params:
                name_key = p.get("map_to") or p.get("name")
                if not name_key:
                    continue
                vals = overrides.get(name_key, p.get("default", []))
                vals = _validate_and_normalize_param_values(name_key, [str(v) for v in vals], p, user_provided=True)
                spec = {"name": name_key, "values": vals}
                if p.get("when") is not None:
                    spec["when"] = p.get("when")
                param_specs.append(spec)
        elif isinstance(overrides, list) and overrides:
            # legacy list of {name, values, when}
            for spec_in in overrides:
                name_key = spec_in.get("name")
                if not name_key:
                    continue
                pdef = next((rp for rp in reg_params if (rp.get("map_to") or rp.get("name")) == name_key), {})
                vals_in = [str(v) for v in (spec_in.get("values") or [])]
                vals = _validate_and_normalize_param_values(name_key, vals_in, pdef, user_provided=True) if pdef else vals_in
                spec = {"name": name_key, "values": vals}
                if spec_in.get("when") is not None:
                    spec["when"] = spec_in.get("when")
                param_specs.append(spec)
            # Add registry params not mentioned to preserve required sweeps with defaults
            mentioned = {s.get("name") for s in param_specs}
            for p in reg_params:
                name_key = p.get("map_to") or p.get("name")
                if not name_key or name_key in mentioned:
                    continue
                vals = _validate_and_normalize_param_values(name_key, [str(v) for v in p.get("default", [])], p, user_provided=False)
                spec = {"name": name_key, "values": vals}
                if p.get("when") is not None:
                    spec["when"] = p.get("when")
                param_specs.append(spec)
        else:
            # No overrides: use registry defaults
            for p in reg_params:
                name_key = p.get("map_to") or p.get("name")
                if not name_key:
                    continue
                vals = _validate_and_normalize_param_values(name_key, [str(v) for v in p.get("default", [])], p, user_provided=False)
                spec = {"name": name_key, "values": vals}
                if p.get("when") is not None:
                    spec["when"] = p.get("when")
                param_specs.append(spec)

        # Initialize CSV header if missing
        if not csv_path.exists():
            with csv_path.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(header)

        # Iterate files and runs for THIS algorithm
        for fpath in sel_files:
            display_base = fpath.name
            combos = _product_sweep(param_specs, base_params)

            # Optional caching for .xz per file
            cached_path: Optional[Path] = None
            if cache and (fpath.suffix == ".xz"):
                with tempfile.NamedTemporaryFile(prefix="cached_", suffix=".cnf", delete=False, dir=str(out_dir)) as tf:
                    cached_path = Path(tf.name)
                try:
                    with open(cached_path, "wb") as out:
                        subprocess.run(["xz", "-dc", "--", str(fpath)], check=True, stdout=out)
                    vprint(verbose, f"Decompressed once: {fpath} -> {cached_path}")
                except subprocess.CalledProcessError:
                    print(f"Failed to decompress {fpath} to {cached_path}", file=sys.stderr)
                    cached_path = None

            for combo in combos:
                ml_list: List[Optional[int]] = memlimits if memlimits else [None]
                for ml in ml_list:
                    # compute auto-generated params and merge into a derived combo
                    aut = _compute_auto_params(reg_algo, combo, out_dir, name, fpath)
                    combo2 = {**combo, **aut}
                    # Pre-check skip-existing if keys provided
                    if keys is not None:
                        key_cols = csv_obj.get("key_cols")
                        pre_vals: List[str] = []
                        unresolved = False
                        for col in header:
                            if col == "file":
                                pre_vals.append(display_base)
                            elif col == "memlimit_mb":
                                pre_vals.append("" if ml is None else str(ml))
                            else:
                                pre_vals.append(combo2.get(col, ""))
                        for idx in key_cols:
                            if pre_vals[idx] == "":
                                unresolved = True
                                break
                        if not unresolved:
                            pre_key = ",".join(pre_vals[i] for i in key_cols)
                            if pre_key in keys:
                                vprint(verbose, f"Skip existing: {pre_key}")
                                continue

                    use_path = cached_path if cached_path is not None else fpath
                    cmd = _format_cmd([str(x) for x in cmd_template], combo2, use_path, bin_path=bin_path)
                    stamp = time.strftime("%Y%m%d-%H%M%S")
                    rand = f"{random.randrange(16**6):06x}"
                    short = _short_hash_tag(combo2, {"file": display_base, "mem": ml})
                    ml_tag = f".m{ml}mb" if ml is not None else ""
                    safe_base = _slug_value(display_base, max_len=80)
                    log = out_dir / f"{safe_base}.{name}.{short}.{rand}{ml_tag}.{stamp}.log"

                    # Compose a descriptive header inside the log
                    header_map = {
                        "timestamp": stamp,
                        "algo": name,
                        "file": display_base,
                        "input_path": str(use_path),
                        "cmd": " ".join(shlex.quote(x) for x in cmd),
                        "params": combo2,
                        "memlimit_mb": None if ml is None else ml,
                    }
                    log_header = "# bench_runner header\n" + json.dumps(header_map, sort_keys=True) + "\n# ---- output ----\n"

                    rc, lines = run_with_streaming(cmd, use_path, log, verbose, memlimit_mb=ml, log_header=log_header)
                    ok = False
                    try:
                        m = _parse_required_keys(lines, required_keys)
                        if m is not None:
                            row_vals: List[str] = []
                            for col in header:
                                if col == "file":
                                    row_vals.append(display_base)
                                elif col == "memlimit_mb":
                                    row_vals.append("" if ml is None else str(ml))
                                else:
                                    row_vals.append(m.get(col, combo2.get(col, "")))
                            if keys is not None:
                                key_cols = csv_obj.get("key_cols")
                                key = ",".join(row_vals[i] for i in key_cols)
                                if key in keys:
                                    vprint(verbose, f"Skip existing: {key}")
                                    ok = True
                                    continue
                            csv_append(csv_path, header, row_vals)
                            ok = True
                    finally:
                        if ok:
                            try:
                                log.unlink()
                            except Exception:
                                pass
                        else:
                            vprint(True, f"[warn] No summary parsed or run failed; kept log: {log}")

            if cached_path is not None:
                try:
                    cached_path.unlink()
                except Exception:
                    pass

    return 0


# -------------- Dynamic algorithm registry mode --------------

def _load_algorithms_registry(path: Optional[Path] = None) -> Dict[str, dict]:
    registry_path = path or (ROOT_DIR / "scripts/benchmarks/configs/algorithms.json")
    if not registry_path.exists():
        raise ConfigError(f"Algorithms registry not found: {registry_path}")
    try:
        import json
        with registry_path.open() as f:
            data = json.load(f)
        algos = data.get("algorithms", [])
        return {a.get("name"): a for a in algos if a.get("name")}
    except Exception as e:
        raise ConfigError(f"Failed to load algorithms registry {registry_path}: {e}")


def _add_core_common(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("-n","--num", type=int, required=True, help="Number of random files to run")
    sp.add_argument("--bin", type=Path, default=None, help="Path to binary; if omitted, auto-discover")
    sp.add_argument("--memlimits", type=parse_int_list, default=[], help="Comma list of MB (Linux only; ignored on macOS)")
    sp.add_argument("--cache", dest="cache", action="store_true", help="Cache decompression (not needed with streaming)")
    sp.add_argument("--no-cache", dest="cache", action="store_false")
    sp.set_defaults(cache=True)
    sp.add_argument("--reuse-files", dest="reuse_files", action="store_true", help="Reuse file list from CSV")
    sp.add_argument("--from-csv", type=Path, dest="reuse_csv", default=None, help="CSV path; defaults to algo CSV when --reuse-files used")
    sp.add_argument("--skip-existing", action="store_true", help="Skip runs already present in CSV")
    sp.add_argument("--dry-run", action="store_true", help="Plan only; print intended commands")
    sp.add_argument("-v","--verbose", action="store_true", help="Verbose output")
    sp.add_argument("--bench-dir", type=Path, default=BENCH_DIR_DEFAULT)
    sp.add_argument("--out-dir", type=Path, default=OUT_DIR_DEFAULT)


def _dest_from_cli(cli_flag: str) -> str:
    # e.g., --max-bufs -> max_bufs
    return cli_flag.lstrip('-').replace('-', '_')


def _parse_type_from_schema(t: str):
    if t == 'int':
        return parse_int_list
    if t == 'float':
        return parse_float_list
    return parse_str_list


def _coerce_numeric(val: str, kind: str) -> float:
    if kind == 'int':
        return float(int(float(val)))
    return float(val)


def _validate_and_normalize_param_values(name: str, values: List[str], pdef: dict, user_provided: bool) -> List[str]:
    """Apply normalization and constraints from pdef to the list of values.
    Supports:
      - pdef.normalize == 'tau' (keeps >=2 or 'inf')
      - pdef.enum: list of allowed string values
      - pdef.allow_inf: bool (accept case-insensitive 'inf')
      - pdef.numeric: 'int'|'float' (coerce strings to numeric for comparison)
      - pdef.min / pdef.max: inclusive bounds for numeric values
    On any invalid input provided by the user, raise ConfigError.
    Returns list of stringified values for downstream usage.
    """
    raw_vals = [str(v) for v in values]
    if not raw_vals:
        return []
    # Enum constraint
    enum = pdef.get('enum')
    if enum:
        allowed = [str(x) for x in enum]
        bad = [v for v in raw_vals if v not in allowed]
        if bad:
            raise ConfigError(f"Invalid values for {name}: {','.join(bad)} (allowed: {','.join(allowed)})")
    # Numeric constraints (with optional allow_inf)
    allow_inf = bool(pdef.get('allow_inf', False))
    numeric_kind = pdef.get('numeric')  # 'int'|'float' or None
    vmin = pdef.get('min', None)
    vmax = pdef.get('max', None)
    if numeric_kind or vmin is not None or vmax is not None:
        checked: List[str] = []
        for v in raw_vals:
            if allow_inf and v.lower() == 'inf':
                checked.append('inf')
                continue
            # Validate numeric
            try:
                num = _coerce_numeric(v, numeric_kind or 'float')
            except Exception:
                raise ConfigError(f"Value for {name} must be {numeric_kind or 'numeric'}: {v}")
            if vmin is not None and num < float(vmin):
                raise ConfigError(f"Value for {name} below minimum {vmin}: {v}")
            if vmax is not None and num > float(vmax):
                raise ConfigError(f"Value for {name} above maximum {vmax}: {v}")
            # Round/normalize back to int if requested
            if numeric_kind == 'int':
                v = str(int(num))
            else:
                v = str(v)
            checked.append(v)
        raw_vals = checked
    return raw_vals


def _discover_bin_from_cfg(algo_name: str, algo_cfg: dict, explicit: Optional[Path]) -> Optional[Path]:
    if explicit is not None:
        return explicit
    # Try discover list from cfg
    for c in algo_cfg.get("discover", []) or []:
        cand = (ROOT_DIR / c)
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    # fallback to dynamic discover by name (registry discover or generic search under build/)
    return _discover_bin_by_name(algo_name)


def run_algorithm_from_registry(algo_name: str, ns: argparse.Namespace, algo_cfg: dict) -> int:
    ensure_out_dir(ns.out_dir)

    # Binary
    bin_path = _discover_bin_from_cfg(algo_name, algo_cfg, ns.bin)
    if not bin_path:
        print(f"Could not find binary for {algo_name}. Build and/or pass --bin", file=sys.stderr)
        return 2

    # Files
    all_files = list_bench_files(ns.bench_dir)
    if not all_files:
        print(f"No benchmark files found in {ns.bench_dir}", file=sys.stderr)
        return 4

    # CSV config
    csv_cfg = algo_cfg.get("csv", {})
    header: List[str] = csv_cfg.get("header") or []
    required_keys: List[str] = csv_cfg.get("required_keys") or []
    if not header or not required_keys:
        raise ConfigError(f"Algorithm '{algo_name}' missing csv.header or csv.required_keys")
    csv_name = csv_cfg.get("path") or f"{algo_name}_results.csv"
    csv_path = ns.out_dir / csv_name
    # Initialize header if missing
    if not csv_path.exists():
        with csv_path.open("w", newline="") as f:
            w = csv.writer(f); w.writerow(header)
    keys = build_keys_set(csv_path, csv_cfg.get("key_cols", [])) if ns.skip_existing else None

    # Select files
    reuse_csv = ns.reuse_csv if ns.reuse_files else None
    sel_files = select_files(all_files, ns.num, reuse_csv, ns.bench_dir, ns.verbose)

    # Build param specs from CLI args according to schema
    base_params: Dict[str, str] = {k: str(v) for k, v in (algo_cfg.get("base_params") or {}).items()}
    param_specs: List[dict] = []
    params_schema: List[dict] = algo_cfg.get("params", [])
    # Collect values from ns
    for pdef in params_schema:
        cli = pdef.get("cli")
        name = pdef.get("name")
        map_to = pdef.get("map_to") or name
        if not cli or not name:
            raise ConfigError(f"Param definition requires 'name' and 'cli': {pdef}")
        dest = _dest_from_cli(cli)
        values = getattr(ns, dest, None)
        if values is None:
            # fall back to config default
            values = pdef.get("default", [])
        # Normalize/validate against schema
        user_provided = getattr(ns, dest, None) is not None
        values = _validate_and_normalize_param_values(map_to, [str(v) for v in values], pdef, user_provided)
        # Skip if no values remain
        if not values:
            continue
        spec = {"name": map_to, "values": values}
        if pdef.get("when") is not None:
            spec["when"] = pdef.get("when")
        param_specs.append(spec)

    # Iterate selections
    for fpath in sel_files:
        display_base = fpath.name
        # Optional per-file cache for .xz
        cached_path: Optional[Path] = None
        if ns.cache and (fpath.suffix == '.xz') and (not ns.dry_run):
            with tempfile.NamedTemporaryFile(prefix='cached_', suffix='.cnf', delete=False, dir=str(ns.out_dir)) as tf:
                cached_path = Path(tf.name)
            try:
                with open(cached_path, 'wb') as out:
                    subprocess.run(["xz","-dc","--",str(fpath)], check=True, stdout=out)
                vprint(ns.verbose, f"Decompressed once: {fpath} -> {cached_path}")
            except subprocess.CalledProcessError:
                print(f"Failed to decompress {fpath} to {cached_path}", file=sys.stderr)
                cached_path = None

        combos = _product_sweep(param_specs, base_params)
        for combo in combos:
            memlist: List[Optional[int]] = ns.memlimits if ns.memlimits else [None]
            for ml in memlist:
                # compute auto-generated params for registry mode
                aut = _compute_auto_params(algo_cfg, combo, ns.out_dir, algo_name, fpath)
                combo2 = {**combo, **aut}
                use_path = cached_path if cached_path is not None else fpath
                cmd_template: List[str] = [str(x) for x in (algo_cfg.get("cmd_template") or [])]
                cmd = _format_cmd(cmd_template, combo2, use_path, bin_path=bin_path)
                # Log path: include params
                stamp = time.strftime("%Y%m%d-%H%M%S")
                params_tag = _params_tag(combo2, exclude_keys=["comp_out_dir", "comp_base"]) 
                ml_tag = f".mem{ml}mb" if ml is not None else ""
                safe_base = _slug_value(display_base, max_len=80)
                rand = f"{random.randrange(16**6):06x}"
                short = _short_hash_tag(combo2, {"file": display_base, "mem": ml})
                log = ns.out_dir / f"{safe_base}.{algo_name}.{short}.{rand}{ml_tag}.{stamp}.log"

                if ns.dry_run:
                    vprint(True, "RUN:", " ".join(shlex.quote(x) for x in cmd))
                    continue

                # Pre-run skip-existing attempt
                if keys is not None:
                    key_cols = csv_cfg.get("key_cols", [])
                    pre_vals: List[str] = []
                    for col in header:
                        if col == "file":
                            pre_vals.append(display_base)
                        elif col == "memlimit_mb":
                            pre_vals.append("" if ml is None else str(ml))
                        else:
                            pre_vals.append(combo2.get(col, ""))
                    if all(pre_vals[i] != "" for i in key_cols):
                        pre_key = ",".join(pre_vals[i] for i in key_cols)
                        if pre_key in keys:
                            vprint(ns.verbose, f"Skip existing: {pre_key}")
                            continue

                header_map = {
                    "timestamp": stamp,
                    "algo": algo_name,
                    "file": display_base,
                    "input_path": str(use_path),
                    "cmd": " ".join(shlex.quote(x) for x in cmd),
                    "params": combo2,
                    "memlimit_mb": None if ml is None else ml,
                }
                log_header = "# bench_runner header\n" + json.dumps(header_map, sort_keys=True) + "\n# ---- output ----\n"
                rc, lines = run_with_streaming(cmd, use_path, log, ns.verbose, memlimit_mb=ml, log_header=log_header)
                ok = False
                try:
                    m = _parse_required_keys(lines, required_keys)
                    if m is not None:
                        row_vals: List[str] = []
                        for col in header:
                            if col == "file": row_vals.append(display_base)
                            elif col == "memlimit_mb": row_vals.append("" if ml is None else str(ml))
                            else: row_vals.append(m.get(col, combo2.get(col, "")))
                        # Post-run skip-existing (safety)
                        if keys is not None:
                            key_cols = csv_cfg.get("key_cols", [])
                            key = ",".join(row_vals[i] for i in key_cols)
                            if key in keys:
                                vprint(ns.verbose, f"Skip existing: {key}")
                                ok = True
                                continue
                        csv_append(csv_path, header, row_vals)
                        ok = True
                finally:
                    if ok:
                        try: log.unlink()
                        except Exception: pass
                    else:
                        vprint(True, f"[warn] No summary parsed or run failed; kept log: {log}")

        if cached_path is not None:
            try:
                cached_path.unlink()
            except Exception:
                pass

    return 0


# -------------- CLI --------------

def parse_int_list(s: str) -> List[int]:
    return [int(x) for x in s.split(',') if x != '']

def parse_float_list(s: str) -> List[float]:
    return [float(x) for x in s.split(',') if x != '']

def parse_str_list(s: str) -> List[str]:
    return [x.strip() for x in s.split(',') if x.strip() != '']


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark runner")
    sub = p.add_subparsers(dest="algo", required=True)

    # Use shared core common options for dynamic algorithms

    # Dynamic algorithms from registry
    try:
        registry = _load_algorithms_registry()
    except Exception:
        registry = {}
    builtins = {"config"}
    for name, cfg in registry.items():
        if name in builtins:
            continue
        sp_dyn = sub.add_parser(name, help=cfg.get("help", f"Run {name}"))
        _add_core_common(sp_dyn)
        # add params declared in registry
        for pdef in cfg.get("params", []) or []:
            cli = pdef.get("cli")
            if not cli:
                continue
            ptype = _parse_type_from_schema(pdef.get("type", "string"))
            default = pdef.get("default", [])
            help_text = pdef.get("help") or pdef.get("name") or cli
            sp_dyn.add_argument(cli, type=ptype, default=default, help=help_text)

    # config-driven batch mode
    sp_cfg = sub.add_parser("config", help="Run algorithms from a JSON/YAML config file")
    sp_cfg.add_argument("--file", type=Path, required=True, help="Path to config file (.json or .yaml)")
    sp_cfg.add_argument("-v","--verbose", action="store_true")

    ns = p.parse_args(argv)

    # Normalize reuse_csv defaults for dynamic algorithms
    if ns.algo in registry:
        algo_cfg = registry[ns.algo]
        csv_path_name = (algo_cfg.get("csv", {}) or {}).get("path") or f"{ns.algo}_results.csv"
        if ns.reuse_files and ns.reuse_csv is None:
            ns.reuse_csv = OUT_DIR_DEFAULT / csv_path_name

    # Dispatch
    if ns.algo == "config":
        return run_from_config(ns.file, verbose=ns.verbose)
    if ns.algo in registry:
        return run_algorithm_from_registry(ns.algo, ns, registry[ns.algo])
    # Should not reach here
    print(f"Unknown algorithm: {ns.algo}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
