#!/usr/bin/env bash
set -euo pipefail

# Run vig_info on N random benchmarks from the benchmarks/ folder.
# For each file, test both --naive and --opt across tau, threads, and maxbuf.
# Results are appended as CSV and per-run logs under scripts/benchmarks/out/.
#
# Usage:
#   scripts/benchmarks/run_vig_info_random.sh -n 5 \
#     --bin build/algorithms/vig_info/vig_info \
#     --taus 1,2,inf \
#     --threads 1,2,4 \
#     --maxbufs 20000000,50000000,100000000 \
#     --memlimits 2048,4096
#
# Notes:
# - If --bin is not provided, tries common default locations.
# - Requires xz to be installed for decompression.
# - Input .cnf.xz or .cnf are supported. Decompression streamed to stdin.

N=0
BIN=""
TAUS=(3 5 10 inf)
THREADS=(1 2 4)
MAXBUFS=(50000000 100000000)
MEMLIMITS=() # in MB; if empty, no OS-level limit applied
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BENCH_DIR="$ROOT_DIR/benchmarks"
OUT_DIR="$ROOT_DIR/scripts/benchmarks/out"
CSV="$OUT_DIR/results.csv"

usage() {
  echo "Usage: $0 -n N [--bin PATH] [--taus a,b,c] [--threads a,b,c] [--maxbufs a,b,c] [--memlimits mb,mb]" >&2
  echo "       tau must be >= 3 or 'inf' (since clauses of size < 2 are irrelevant)." >&2
  exit 1
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--num)
      N=${2:-0}; shift 2 ;;
    --bin)
      BIN=${2:-""}; shift 2 ;;
    --taus)
      IFS=',' read -r -a TAUS <<< "${2:-}"; shift 2 ;;
    --threads)
      IFS=',' read -r -a THREADS <<< "${2:-}"; shift 2 ;;
    --maxbufs)
      IFS=',' read -r -a MAXBUFS <<< "${2:-}"; shift 2 ;;
    --memlimits)
      IFS=',' read -r -a MEMLIMITS <<< "${2:-}"; shift 2 ;;
    -h|--help)
      usage ;;
    *)
      echo "Unknown arg: $1" >&2; usage ;;
  esac
done

if [[ "$N" -le 0 ]]; then
  echo "Error: -n N must be > 0" >&2
  usage
fi

mkdir -p "$OUT_DIR"

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
    "$ROOT_DIR/build/algorithms/vig_info/vig_info"
    "$ROOT_DIR/build/algorithms/vig_info/Debug/vig_info"
    "$ROOT_DIR/build/algorithms/vig_info/Release/vig_info"
    "$ROOT_DIR/build/vig_info"
  )
  for c in "${cand[@]}"; do
    if [[ -x "$c" ]]; then BIN="$c"; break; fi
  done
fi

if [[ -z "$BIN" ]]; then
  echo "Could not find vig_info binary. Build the project and/or pass --bin" >&2
  exit 2
fi

if ! command -v xz >/dev/null 2>&1; then
  echo "xz not found. Please install xz." >&2
  exit 3
fi

# Prepare CSV header if new
if [[ ! -f "$CSV" ]]; then
  echo "file,impl,tau,threads,maxbuf,memlimit_mb,vars,edges,time_sec,agg_memory" > "$CSV"
fi

# Collect candidate files
FILES=()
while IFS= read -r __path; do
  FILES+=("$__path")
done < <(find "$BENCH_DIR" -type f \( -name '*.cnf' -o -name '*.cnf.xz' \) | sort)
if [[ ${#FILES[@]} -eq 0 ]]; then
  echo "No benchmark files found in $BENCH_DIR" >&2
  exit 4
fi

# Pick N random files
shuf_files=("${FILES[@]}")
if command -v gshuf >/dev/null 2>&1; then
  shuf_files=()
  while IFS= read -r __line; do shuf_files+=("$__line"); done < <(printf '%s\n' "${FILES[@]}" | gshuf)
elif command -v shuf >/dev/null 2>&1; then
  shuf_files=()
  while IFS= read -r __line; do shuf_files+=("$__line"); done < <(printf '%s\n' "${FILES[@]}" | shuf)
else
  # Portable fallback using awk+sort
  shuf_files=()
  while IFS= read -r __line; do shuf_files+=("$__line"); done < <(printf '%s\n' "${FILES[@]}" | awk 'BEGIN{srand()} {printf("%f\t%s\n", rand(), $0)}' | sort -k1,1g | cut -f2-)
fi
sel=("${shuf_files[@]:0:$N}")

run_case() {
  local filepath="$1" impl="$2" tau="$3" threads="$4" maxbuf="$5" memlimit_mb="$6"
  local base="$(basename "$filepath")"
  local stamp="$(date +%Y%m%d-%H%M%S)"
  local ml_tag
  if [[ -n "$memlimit_mb" ]]; then ml_tag=".mem${memlimit_mb}mb"; else ml_tag=""; fi
  local log="$OUT_DIR/${base}.${impl}.tau${tau}.t${threads}.mb${maxbuf}${ml_tag}.${stamp}.log"

  # Build the command, optionally wrapping with ulimit.
  local run_cmd
  if [[ -n "$memlimit_mb" ]]; then
    # OS-level memory limit best-effort:
    # - Linux: ulimit -Sv <KB>
    # - macOS (Darwin): -v unsupported; skip with a one-time warning
    local os
    os=$(uname -s || echo "")
    if [[ "$os" == "Darwin" ]]; then
      if [[ -z "${_VIG_INFO_MEM_WARNED:-}" ]]; then
        echo "[warn] OS memlimit not supported on macOS; ignoring --memlimits (using algorithm maxbuf only)" >&2
        _VIG_INFO_MEM_WARNED=1
      fi
      run_cmd=("$BIN" -i - -tau "$tau" ${impl} ${threads:+-t "$threads"} ${maxbuf:+-maxbuf "$maxbuf"})
      run_cmd_file=("$BIN" -i "$filepath" -tau "$tau" ${impl} ${threads:+-t "$threads"} ${maxbuf:+-maxbuf "$maxbuf"})
      memlimit_mb="" # clear since it's ignored on macOS
    else
      local kb=$(( memlimit_mb * 1024 ))
      run_cmd=(bash -c "ulimit -Sv ${kb} && exec \"$BIN\" -i - -tau \"$tau\" ${impl} ${threads:+-t \"$threads\"} ${maxbuf:+-maxbuf \"$maxbuf\"}")
      run_cmd_file=(bash -c "ulimit -Sv ${kb} && exec \"$BIN\" -i \"$filepath\" -tau \"$tau\" ${impl} ${threads:+-t \"$threads\"} ${maxbuf:+-maxbuf \"$maxbuf\"}")
    fi
  else
    run_cmd=("$BIN" -i - -tau "$tau" ${impl} ${threads:+-t "$threads"} ${maxbuf:+-maxbuf "$maxbuf"})
    run_cmd_file=("$BIN" -i "$filepath" -tau "$tau" ${impl} ${threads:+-t "$threads"} ${maxbuf:+-maxbuf "$maxbuf"})
  fi

  if [[ "$filepath" == *.xz ]]; then
    # Stream decompress and pipe to program using stdin
    if ! xz -dc -- "$filepath" | "${run_cmd[@]}" | tee "$log" ; then
      echo "Run failed: $filepath ($impl tau=$tau t=$threads mb=$maxbuf)" >&2
      return 1
    fi
  else
    if ! "${run_cmd_file[@]}" | tee "$log" ; then
      echo "Run failed: $filepath ($impl tau=$tau t=$threads mb=$maxbuf)" >&2
      return 1
    fi
  fi

  # Parse a summary line like:
  # vars=... edges=... time_sec=... impl=... tau=... threads=... agg_memory=...
  local summary
  summary=$(grep -E "vars=[0-9]+ .*edges=[0-9]+ .*time_sec=[0-9.]+ .*impl=(naive|opt) .*tau=(-1|[0-9]+) .*threads=(-1|[0-9]+) .*agg_memory=[0-9]+" "$log" | tail -n 1 || true)
  if [[ -n "$summary" ]]; then
    # Extract fields
    local vars edges time_sec impl_out tau_out threads_out agg
    vars=$(sed -nE 's/.*vars=([0-9]+).*/\1/p' <<< "$summary")
    edges=$(sed -nE 's/.*edges=([0-9]+).*/\1/p' <<< "$summary")
    time_sec=$(sed -nE 's/.*time_sec=([0-9.]+).*/\1/p' <<< "$summary")
    impl_out=$(sed -nE 's/.*impl=([a-z]+).*/\1/p' <<< "$summary")
    tau_out=$(sed -nE 's/.*tau=([-0-9]+).*/\1/p' <<< "$summary")
    threads_out=$(sed -nE 's/.*threads=([-0-9]+).*/\1/p' <<< "$summary")
    agg=$(sed -nE 's/.*agg_memory=([0-9]+).*/\1/p' <<< "$summary")
  echo "$base,$impl_out,$tau_out,$threads_out,$maxbuf,${memlimit_mb:-},$vars,$edges,$time_sec,$agg" >> "$CSV"
  fi
}

# Iterate selections
for f in "${sel[@]}"; do
  # naive: threads fixed to 1; ignore maxbuf; sweep memlimits if provided
  for tau in "${TAUS[@]}"; do
    if [[ ${#MEMLIMITS[@]} -gt 0 ]]; then
      for ml in "${MEMLIMITS[@]}"; do
        run_case "$f" "--naive" "$tau" 1 "" "$ml" || true
      done
    else
      run_case "$f" "--naive" "$tau" 1 "" "" || true
    fi
  done

  # optimized: vary tau, threads, maxbuf; sweep memlimits if provided
  for tau in "${TAUS[@]}"; do
    for t in "${THREADS[@]}"; do
      for mb in "${MAXBUFS[@]}"; do
        if [[ ${#MEMLIMITS[@]} -gt 0 ]]; then
          for ml in "${MEMLIMITS[@]}"; do
            run_case "$f" "--opt" "$tau" "$t" "$mb" "$ml" || true
          done
        else
          run_case "$f" "--opt" "$tau" "$t" "$mb" "" || true
        fi
      done
    done
  done

done

echo "Done. Results: $CSV"
