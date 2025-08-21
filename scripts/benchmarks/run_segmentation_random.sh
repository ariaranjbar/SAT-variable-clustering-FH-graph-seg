#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib_bench.sh"

# Run segmentation on N random benchmarks from the benchmarks/ folder.
# For each file, test the selected implementation(s) across tau, k, threads, and maxbuf.
# Results are appended as CSV and per-run logs under scripts/benchmarks/out/.
#
# Usage:
#   scripts/benchmarks/run_segmentation_random.sh -n 5 \
#     --bin build/algorithms/segmentation/segmentation \
#     --taus 3,5,10,inf \
#     --ks 25,50,100 \
#     --threads 1,2,4 \
#     --maxbufs 20000000,50000000,100000000 \
#     --memlimits 2048,4096
#     --implementations naive,opt \
#
# Notes:
# - If --bin is not provided, tries common default locations.
# - Requires xz to be installed for decompression.
# - Input .cnf.xz or .cnf are supported. Decompression streamed to stdin.

N=0
BIN=""
TAUS=(3 5 10 inf)
KS=(50)
THREADS=(1 2 4)
MAXBUFS=(50000000 100000000)
MEMLIMITS=() # in MB; if empty, no OS-level limit applied
CACHE_DECOMPRESS=1 # default: cache .xz -> .cnf once per file
REUSE_CSV=""      # when set, reuse file list from this CSV (defaults to $CSV)
SKIP_EXISTING=0    # when 1, skip runs already present in CSV
VERBOSE=0
DRY_RUN=0
IMPLS=(naive opt)
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BENCH_DIR="$ROOT_DIR/benchmarks"
OUT_DIR="$ROOT_DIR/scripts/benchmarks/out"
CSV="$OUT_DIR/segmentation_results.csv"

usage() {
  echo "Usage: $0 -n N [--bin PATH] [--taus a,b,c] [--ks a,b,c] [--threads a,b,c] [--maxbufs a,b,c] [--memlimits mb,mb] [--implementations naive[,opt]] [--cache|--no-cache] [--reuse-files] [--from-csv PATH] [--skip-existing] [--dry-run] [--verbose|-v]" >&2
  echo "       tau must be >= 3 or 'inf' (since clauses of size < 2 are irrelevant)." >&2
  exit 1
}

# vprint comes from lib_bench.sh

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num)
      N=${2:-0}; shift 2 ;;
    --bin)
      BIN=${2:-""}; shift 2 ;;
    --taus)
      IFS=',' read -r -a TAUS <<< "${2:-}"; shift 2 ;;
    --ks)
      IFS=',' read -r -a KS <<< "${2:-}"; shift 2 ;;
    --threads)
      IFS=',' read -r -a THREADS <<< "${2:-}"; shift 2 ;;
    --maxbufs)
      IFS=',' read -r -a MAXBUFS <<< "${2:-}"; shift 2 ;;
    --memlimits)
      IFS=',' read -r -a MEMLIMITS <<< "${2:-}"; shift 2 ;;
    --implementations)
      IFS=',' read -r -a IMPLS <<< "${2:-}"; shift 2 ;;
    --cache)
      CACHE_DECOMPRESS=1; shift ;;
    --no-cache)
      CACHE_DECOMPRESS=0; shift ;;
    --reuse-files)
      REUSE_CSV="__DEFAULT__"; shift ;;
    --from-csv)
      REUSE_CSV=${2:-"__DEFAULT__"}; shift 2 ;;
    --skip-existing)
      SKIP_EXISTING=1; shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --verbose|-v)
      VERBOSE=1; shift ;;
    -h|--help)
      usage ;;
    *)
      echo "Unknown arg: $1" >&2; usage ;;
  esac
done
# Validate IMPLS values (allow only naive or opt); default to both if empty
if [[ ${#IMPLS[@]} -eq 0 ]]; then
  IMPLS=(naive opt)
fi
for __impl in ${IMPLS[@]+"${IMPLS[@]}"}; do
  case "$__impl" in
    naive|opt) ;;
    *) echo "Error: --implementations entries must be 'naive' or 'opt' (comma-separated)" >&2; exit 1 ;;
  esac
done

# Helper to check membership in IMPLS
has_impl() {
  local name="$1"
  for x in ${IMPLS[@]+"${IMPLS[@]}"}; do
    if [[ "$x" == "$name" ]]; then return 0; fi
  done
  return 1
}

if [[ "$N" -le 0 ]]; then
  echo "Error: -n N must be > 0" >&2
  usage
fi

mkdir -p "$OUT_DIR"
TMP_DIR=""
if [[ "$CACHE_DECOMPRESS" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  TMP_DIR="$OUT_DIR/tmp.$$.${RANDOM}"
  mkdir -p "$TMP_DIR"
  # Ensure cleanup
  trap 'rm -rf "$TMP_DIR"' EXIT
fi

# Normalize and validate TAUS: keep numeric >=3 and 'inf'
norm_taus=()
for _tau in "${TAUS[@]}"; do
  case "$_tau" in
    inf|INF)
      norm_taus+=(inf)
      ;;
    *)
      # accept only non-negative integers >= 3
      case "$_tau" in
        ''|*[!0-9]*)
          echo "[warn] Skipping invalid tau '$_tau' (not an integer or 'inf')" >&2
          ;;
        *)
          if [[ $_tau -ge 3 ]]; then
            norm_taus+=("$_tau")
          else
            echo "[warn] Skipping tau=$_tau (<3)" >&2
          fi
          ;;
      esac
      ;;
  esac
done
if [[ ${#norm_taus[@]} -eq 0 ]]; then
  echo "Error: No valid tau values provided (need >=3 or 'inf')." >&2
  exit 1
fi
TAUS=("${norm_taus[@]}")

# Resolve binary if not given
if [[ -z "$BIN" ]]; then
  cand=(
    "$ROOT_DIR/build/algorithms/segmentation/segmentation"
    "$ROOT_DIR/build/algorithms/segmentation/Debug/segmentation"
    "$ROOT_DIR/build/algorithms/segmentation/Release/segmentation"
    "$ROOT_DIR/build/segmentation"
  )
  for c in "${cand[@]}"; do
    if [[ -x "$c" ]]; then BIN="$c"; break; fi
  done
fi

if [[ -z "$BIN" ]]; then
  echo "Could not find segmentation binary. Build the project and/or pass --bin" >&2
  exit 2
fi

if ! command -v xz >/dev/null 2>&1; then
  echo "xz not found. Please install xz." >&2
  exit 3
fi

# Prepare CSV header if new
if [[ ! -f "$CSV" && "$DRY_RUN" -eq 0 ]]; then
  echo "file,impl,tau,k,threads,maxbuf,memlimit_mb,vars,edges,comps,total_sec,parse_sec,vig_build_sec,seg_sec,agg_memory" > "$CSV"
fi

# Collect all candidate files (full paths)
ALL_FILES=()
while IFS= read -r __path; do
  ALL_FILES+=("$__path")
done < <(find "$BENCH_DIR" -type f \( -name '*.cnf' -o -name '*.cnf.xz' \) | sort)
if [[ ${#ALL_FILES[@]} -eq 0 ]]; then
  echo "No benchmark files found in $BENCH_DIR" >&2
  exit 4
fi

# Build selection set
sel=()
if [[ -n "$REUSE_CSV" ]]; then
  # Determine CSV path
  if [[ "$REUSE_CSV" == "__DEFAULT__" ]]; then REUSE_CSV="$CSV"; fi
  if [[ ! -f "$REUSE_CSV" ]]; then
    echo "Reuse requested but CSV not found: $REUSE_CSV" >&2
    exit 5
  fi
  # Get unique basenames from CSV (skip header)
  basenames=()
  while IFS= read -r bn; do
    [[ -z "$bn" ]] && continue
    basenames+=("$bn")
  done < <(tail -n +2 "$REUSE_CSV" | cut -d, -f1 | sort -u)
  # Resolve each basename to a file path under BENCH_DIR (first match)
  for bn in ${basenames[@]+"${basenames[@]}"}; do
    found=""
    for p in "${ALL_FILES[@]}"; do
      if [[ "$(basename "$p")" == "$bn" ]]; then found="$p"; break; fi
    done
    if [[ -n "$found" ]]; then sel+=("$found"); else echo "[warn] Not found in benchmarks/: $bn" >&2; fi
  done
  # Note: ignore -n; selection is based on CSV
  vprint "Reusing ${#sel[@]} files from CSV: $REUSE_CSV (ignoring -n)"
else
  # Randomly pick N
  shuf_files=()
  while IFS= read -r __line; do shuf_files+=("$__line"); done < <(printf '%s\n' "${ALL_FILES[@]}" | bench_shuffle_lines)
  sel=("${shuf_files[@]:0:$N}")
  vprint "Selected ${#sel[@]} random files (requested -n $N)"
fi

# Build skip-existing keys set if requested
KEYS_FILE=""
if [[ "$SKIP_EXISTING" -eq 1 ]]; then
  if [[ -f "$CSV" ]]; then
    KEYS_FILE="$OUT_DIR/.seg_keys.$$.txt"
    # header: file,impl,tau,k,threads,maxbuf,...
    tail -n +2 "$CSV" | awk -F, '{print $1","$2","$3","$4","$5","$6}' | sort -u > "$KEYS_FILE"
    trap 'rm -f "$KEYS_FILE"; rm -rf "$TMP_DIR"' EXIT
  else
    echo "[info] --skip-existing set but no CSV yet; nothing to skip"
  fi
fi

run_case() {
  local filepath="$1" display_base="$2" impl="$3" tau="$4" kval="$5" threads="$6" maxbuf="$7" memlimit_mb="$8"
  local base="$display_base"
  local stamp="$(date +%Y%m%d-%H%M%S)"
  local ml_tag
  if [[ -n "$memlimit_mb" ]]; then ml_tag=".mem${memlimit_mb}mb"; else ml_tag=""; fi
  local log="$OUT_DIR/${base}.${impl}.tau${tau}.k${kval}.t${threads}.mb${maxbuf}${ml_tag}.${stamp}.log"
  local ok=0

  # Build the command, optionally wrapping with ulimit.
  local run_cmd
  if [[ -n "$memlimit_mb" ]]; then
    # OS-level memory limit best-effort:
    # - Linux: ulimit -Sv <KB>
    # - macOS (Darwin): -v unsupported; skip with a one-time warning
    local os
    os=$(uname -s || echo "")
    if [[ "$os" == "Darwin" ]]; then
      if [[ -z "${_SEG_MEM_WARNED:-}" ]]; then
        echo "[warn] OS memlimit not supported on macOS; ignoring --memlimits (using algorithm maxbuf only)" >&2
        _SEG_MEM_WARNED=1
      fi
      run_cmd=("$BIN" -i - --tau "$tau" --k "$kval" ${impl} ${threads:+-t "$threads"} ${maxbuf:+--maxbuf "$maxbuf"})
      run_cmd_file=("$BIN" -i "$filepath" --tau "$tau" --k "$kval" ${impl} ${threads:+-t "$threads"} ${maxbuf:+--maxbuf "$maxbuf"})
      memlimit_mb="" # clear since it's ignored on macOS
    else
      local kb=$(( memlimit_mb * 1024 ))
      run_cmd=(bash -c "ulimit -Sv ${kb} && exec \"$BIN\" -i - --tau \"$tau\" --k \"$kval\" ${impl} ${threads:+-t \"$threads\"} ${maxbuf:+--maxbuf \"$maxbuf\"}")
      run_cmd_file=(bash -c "ulimit -Sv ${kb} && exec \"$BIN\" -i \"$filepath\" --tau \"$tau\" --k \"$kval\" ${impl} ${threads:+-t \"$threads\"} ${maxbuf:+--maxbuf \"$maxbuf\"}")
    fi
  else
    run_cmd=("$BIN" -i - --tau "$tau" --k "$kval" ${impl} ${threads:+-t "$threads"} ${maxbuf:+--maxbuf "$maxbuf"})
    run_cmd_file=("$BIN" -i "$filepath" --tau "$tau" --k "$kval" ${impl} ${threads:+-t "$threads"} ${maxbuf:+--maxbuf "$maxbuf"})
  fi

  vprint "PLAN file=$display_base impl=${impl#--} tau=$tau k=$kval threads=$threads maxbuf=${maxbuf:-} memlimit_mb=${memlimit_mb:-}"

  if [[ "$DRY_RUN" -eq 1 ]]; then
    # Print a representative command (not exact quoting) without executing.
    if [[ "$filepath" == *.xz ]]; then
      echo "DRY RUN: xz -dc -- '$display_base' | $BIN -i - --tau $tau --k $kval ${impl} ${threads:+-t $threads} ${maxbuf:+--maxbuf $maxbuf}" >&2
    else
      echo "DRY RUN: $BIN -i '$display_base' --tau $tau --k $kval ${impl} ${threads:+-t $threads} ${maxbuf:+--maxbuf $maxbuf}" >&2
    fi
    return 0
  fi

  if [[ "$filepath" == *.xz ]]; then
    # Stream decompress and pipe to program using stdin
    if ! xz -dc -- "$filepath" | "${run_cmd[@]}" | tee "$log" ; then
      echo "Run failed: $filepath ($impl tau=$tau k=$kval t=$threads mb=$maxbuf)" >&2
      return 1
    fi
  else
    if ! "${run_cmd_file[@]}" | tee "$log" ; then
      echo "Run failed: $filepath ($impl tau=$tau k=$kval t=$threads mb=$maxbuf)" >&2
      return 1
    fi
  fi

  # Parse a summary line; allow flexible field order.
  # We only require presence of vars, edges, comps, k, impl, threads, agg_memory, and total_sec.
  local summary
  summary=$(grep -E "vars=[0-9]+ .*edges=[0-9]+ .*comps=[0-9]+ .*k=[0-9.]+ .*total_sec=[0-9.]+ .*impl=(naive|opt) .*threads=(-1|[0-9]+) .*agg_memory=[0-9]+" "$log" | tail -n 1 || true)
  if [[ -n "$summary" ]]; then
    # Extract fields
    local vars edges comps total_sec parse_sec vig_build_sec seg_sec impl_out tau_out threads_out agg
    vars=$(sed -nE 's/.*vars=([0-9]+).*/\1/p' <<< "$summary")
    edges=$(sed -nE 's/.*edges=([0-9]+).*/\1/p' <<< "$summary")
    comps=$(sed -nE 's/.*comps=([0-9]+).*/\1/p' <<< "$summary")
    total_sec=$(sed -nE 's/.*total_sec=([0-9.]+).*/\1/p' <<< "$summary")
    parse_sec=$(sed -nE 's/.*parse_sec=([0-9.]+).*/\1/p' <<< "$summary")
    vig_build_sec=$(sed -nE 's/.*vig_build_sec=([0-9.]+).*/\1/p' <<< "$summary")
    seg_sec=$(sed -nE 's/.*seg_sec=([0-9.]+).*/\1/p' <<< "$summary")
    impl_out=$(sed -nE 's/.*impl=([a-z]+).*/\1/p' <<< "$summary")
    tau_out=$(sed -nE 's/.*tau=([-0-9]+).*/\1/p' <<< "$summary")
    threads_out=$(sed -nE 's/.*threads=([-0-9]+).*/\1/p' <<< "$summary")
    k_out=$(sed -nE 's/.*k=([0-9.]+).*/\1/p' <<< "$summary")
    agg=$(sed -nE 's/.*agg_memory=([0-9]+).*/\1/p' <<< "$summary")
    # Ensure empty optional fields render as empty values
    [[ -z "$parse_sec" ]] && parse_sec=""
    [[ -z "$vig_build_sec" ]] && vig_build_sec=""
    [[ -z "$seg_sec" ]] && seg_sec=""
    echo "$base,$impl_out,$tau_out,$k_out,$threads_out,$maxbuf,${memlimit_mb:-},$vars,$edges,$comps,$total_sec,$parse_sec,$vig_build_sec,$seg_sec,$agg" >> "$CSV"
    ok=1
  else
    echo "[warn] No summary line parsed; keeping log: $log" >&2
  fi

  # Cleanup: remove logs for successful runs; keep logs for failures/missing summary
  if [[ $ok -eq 1 ]]; then
    rm -f "$log" || true
  fi
}

# Iterate selections
for f in ${sel[@]+"${sel[@]}"}; do
  # If caching enabled and file is .xz, decompress once to TMP and reuse.
  use_path="$f"
  display_base="$(basename "$f")"
  cached_created=""
  if [[ "$CACHE_DECOMPRESS" -eq 1 && "$f" == *.xz && "$DRY_RUN" -eq 0 ]]; then
    base="$(basename "$f")"
    # Drop trailing .xz -> produce .cnf (or whatever the inner name is)
    cached="$TMP_DIR/${base%.xz}"
    # Only decompress if missing for this run
    if [[ ! -f "$cached" ]]; then
      if ! xz -dc -- "$f" > "$cached"; then
        echo "Failed to decompress $f to $cached" >&2
        continue
      fi
      cached_created="$cached"
      vprint "Decompressed once: $f -> $cached"
    fi
    use_path="$cached"
  fi

  # naive: threads fixed to 1; ignore maxbuf; sweep memlimits if provided
  if has_impl naive; then
    for tau in "${TAUS[@]}"; do
      for kval in "${KS[@]}"; do
        if [[ ${#MEMLIMITS[@]} -gt 0 ]]; then
          for ml in "${MEMLIMITS[@]}"; do
            # Skip if already exists in CSV
            if [[ "$SKIP_EXISTING" -eq 1 && -f "$KEYS_FILE" ]]; then
              ptau="$tau"; [[ "$tau" == "inf" || "$tau" == "INF" ]] && ptau="-1"
              key="$display_base,naive,$ptau,$kval,1,"
              if grep -Fxq -- "$key" "$KEYS_FILE"; then vprint "Skip existing: $key"; continue; fi
            fi
            run_case "$use_path" "$display_base" "--naive" "$tau" "$kval" 1 "" "$ml" || true
          done
        else
          if [[ "$SKIP_EXISTING" -eq 1 && -f "$KEYS_FILE" ]]; then
            ptau="$tau"; [[ "$tau" == "inf" || "$tau" == "INF" ]] && ptau="-1"
            key="$display_base,naive,$ptau,$kval,1,"
            if grep -Fxq -- "$key" "$KEYS_FILE"; then vprint "Skip existing: $key"; continue; fi
          fi
          run_case "$use_path" "$display_base" "--naive" "$tau" "$kval" 1 "" "" || true
        fi
      done
    done
  fi

  # optimized: vary tau, k, threads, maxbuf; sweep memlimits if provided
  if has_impl opt; then
    for tau in "${TAUS[@]}"; do
      for kval in "${KS[@]}"; do
        for t in "${THREADS[@]}"; do
          for mb in "${MAXBUFS[@]}"; do
            if [[ ${#MEMLIMITS[@]} -gt 0 ]]; then
              for ml in "${MEMLIMITS[@]}"; do
                if [[ "$SKIP_EXISTING" -eq 1 && -f "$KEYS_FILE" ]]; then
                  ptau="$tau"; [[ "$tau" == "inf" || "$tau" == "INF" ]] && ptau="-1"
                  key="$display_base,opt,$ptau,$kval,$t,$mb"
                  if grep -Fxq -- "$key" "$KEYS_FILE"; then vprint "Skip existing: $key"; continue; fi
                fi
                run_case "$use_path" "$display_base" "--opt" "$tau" "$kval" "$t" "$mb" "$ml" || true
              done
            else
              if [[ "$SKIP_EXISTING" -eq 1 && -f "$KEYS_FILE" ]]; then
                ptau="$tau"; [[ "$tau" == "inf" || "$tau" == "INF" ]] && ptau="-1"
                key="$display_base,opt,$ptau,$kval,$t,$mb"
                if grep -Fxq -- "$key" "$KEYS_FILE"; then vprint "Skip existing: $key"; continue; fi
              fi
              run_case "$use_path" "$display_base" "--opt" "$tau" "$kval" "$t" "$mb" "" || true
            fi
          done
        done
      done
    done
  fi

  # Per-file cleanup (only remove if created by us; TMP_DIR is removed by trap)
  if [[ -n "$cached_created" && -f "$cached_created" ]]; then
    rm -f "$cached_created" || true
  fi

done

echo "Done. Results: $CSV"
