#!/usr/bin/env bash
# Shared helpers for benchmark scripts
# - vprint: gated verbose logging controlled by VERBOSE=0/1 in caller
# - bench_shuffle_lines: shuffle stdin lines using gshuf/shuf if present, else awk fallback

# Usage in caller:
#   source "$(cd "$(dirname "$0")" && pwd)/lib_bench.sh"
#   VERBOSE=1  # optional
#   vprint "message"
#   mapfile -t shuffled < <(printf '%s\n' "${arr[@]}" | bench_shuffle_lines)

vprint() {
  if [[ "${VERBOSE:-0}" -eq 1 ]]; then
    echo "[info] $*" >&2
  fi
}

bench_shuffle_lines() {
  if command -v gshuf >/dev/null 2>&1; then
    gshuf
  elif command -v shuf >/dev/null 2>&1; then
    shuf
  else
  # Portable fallback using awk+sort (locale-stable numeric sort)
  LC_ALL=C awk 'BEGIN{srand()} {printf("%f\t%s\n", rand(), $0)}' | LC_ALL=C sort -k1,1g | cut -f2-
  fi
}
