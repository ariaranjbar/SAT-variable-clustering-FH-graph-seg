#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--update]

Create/update the 'thesis-bench' conda env from environment.yml and run plots:
  - VIG plots -> scripts/benchmarks/out/vig_info_plots
  - Segmentation plots -> scripts/benchmarks/out/segmentation_plots

Options:
  --update   Update the env from environment.yml if it already exists
USAGE
}

## Create/Update a conda env and run plotting
ENV_NAME="thesis-bench"
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$THIS_DIR/../.." && pwd)"
VIG_CSV_PATH="$ROOT_DIR/scripts/benchmarks/out/vig_info_results.csv"
VIG_OUT_DIR="$ROOT_DIR/scripts/benchmarks/out/vig_info_plots"
# Segmentation inputs/outputs
SEG_CSV_PATH="$ROOT_DIR/scripts/benchmarks/out/segmentation_results.csv"
SEG_OUT_DIR="$ROOT_DIR/scripts/benchmarks/out/segmentation_plots"
CONDARC_FILE="$ROOT_DIR/.condarc"
# Graph visualization inputs/outputs
GRAPHS_DIR="$ROOT_DIR/scripts/benchmarks/out/graphs"
VIS_SCRIPT="$ROOT_DIR/scripts/benchmarks/visualize_graph.py"

info() { printf '[info] %s\n' "$*"; }
warn() { printf '[warn] %s\n' "$*" >&2; }
die() { printf '[error] %s\n' "$*" >&2; exit 1; }

command -v conda >/dev/null 2>&1 || die "conda is not on PATH. Install Miniconda/Anaconda and ensure 'conda' is available."

# Prefer project-local condarc to avoid implicit defaults warnings
if [[ -f "$CONDARC_FILE" ]]; then
  export CONDARC="$CONDARC_FILE"
  info "Using project condarc: $CONDARC"
fi

# Flags
DO_UPDATE=0
if [[ ${1:-} == "--help" || ${1:-} == "-h" ]]; then
  usage
  exit 0
fi
if [[ ${1:-} == "--update" ]]; then
  DO_UPDATE=1
fi

# Ensure env exists
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  info "Using existing conda env: $ENV_NAME"
  if [[ $DO_UPDATE -eq 1 ]]; then
    info "Updating conda env from environment.yml (requested via --update)"
    # Try to update, but don't abort if conda crashes; continue with best-effort
    set +e
    if [[ -f "$THIS_DIR/environment.yml" ]]; then
      conda env update -n "$ENV_NAME" -f "$THIS_DIR/environment.yml"
    else
      warn "environment.yml not found at $THIS_DIR; skipping update"
    fi
    UPDATE_RC=$?
    set -e
    if [[ $UPDATE_RC -ne 0 ]]; then
      warn "'conda env update' failed (rc=$UPDATE_RC). Proceeding without update."
    fi
  else
    info "Skipping env update (pass --update to update from environment.yml)"
  fi
else
  info "Creating conda env: $ENV_NAME"
  # Create from environment.yml; if that fails, fall back to minimal create and install deps
  set +e
  if [[ -f "$THIS_DIR/environment.yml" ]]; then
    conda env create -f "$THIS_DIR/environment.yml"
  else
    warn "environment.yml not found at $THIS_DIR; creating minimal env"
    false
  fi
  CREATE_RC=$?
  set -e
  if [[ $CREATE_RC -ne 0 ]]; then
    info "Fallback: creating minimal env and installing dependencies"
    conda create -y -n "$ENV_NAME" python=3.10
    conda install -y -n "$ENV_NAME" -c conda-forge pandas numpy matplotlib seaborn networkx || true
  fi
fi

###############################################################################
# Activate env and run Python directly (avoid conda run to silence defaults warning)
###############################################################################
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# Ensure required packages are present; install if missing
set +e
python - <<'PY'
import sys
mods = ["pandas", "numpy", "matplotlib", "seaborn", "networkx"]
def is_missing(m):
  try:
    __import__(m)
    return False
  except Exception:
    return True
missing = [m for m in mods if is_missing(m)]
sys.exit(1 if missing else 0)
PY
NEED_INSTALL=$?
set -e
if [[ $NEED_INSTALL -ne 0 ]]; then
  info "Installing missing Python packages into $ENV_NAME"
  conda install -y -n "$ENV_NAME" -c conda-forge pandas numpy matplotlib seaborn networkx || true
fi

# Run plotters
mkdir -p "$VIG_OUT_DIR" "$SEG_OUT_DIR"

if [[ -f "$VIG_CSV_PATH" ]]; then
  info "Running VIG plots -> $VIG_OUT_DIR"
  for impl in opt naive; do
    python "$THIS_DIR/plot_vig_info_results.py" --csv "$VIG_CSV_PATH" --outdir "$VIG_OUT_DIR" --impl "$impl" || warn "VIG plotting failed for impl=$impl"
  done
  info "VIG plots written to $VIG_OUT_DIR"
else
  warn "VIG CSV not found: $VIG_CSV_PATH — skipping VIG plots"
fi

if [[ -f "$SEG_CSV_PATH" ]]; then
  info "Running segmentation plots -> $SEG_OUT_DIR"
  python "$THIS_DIR/plot_segmentation_results.py" --csv "$SEG_CSV_PATH" --outdir "$SEG_OUT_DIR" || warn "Segmentation plotting failed"
  info "Segmentation plots written to $SEG_OUT_DIR"
else
  warn "Segmentation CSV not found: $SEG_CSV_PATH — skipping segmentation plots"
fi

# Visualize graph CSVs if present (pair *node.csv with matching *edges.csv)
if [[ -d "$GRAPHS_DIR" ]]; then
  if [[ -f "$VIS_SCRIPT" ]]; then
    info "Rendering graph visualizations from $GRAPHS_DIR"
    shopt -s nullglob
    count=0
    # Support both singular and plural naming: *node.csv and *nodes.csv
    for node_csv in "$GRAPHS_DIR"/*node.csv "$GRAPHS_DIR"/*nodes.csv; do
      [[ -f "$node_csv" ]] || continue
      case "$node_csv" in
        *.node.csv) edges_csv="${node_csv%.node.csv}.edges.csv" ;;
        *.nodes.csv) edges_csv="${node_csv%.nodes.csv}.edges.csv" ;;
        *) edges_csv="" ;;
      esac
      [[ -n "$edges_csv" && -f "$edges_csv" ]] || continue
      out_img="${node_csv%.csv}.png"
      title="$(basename "${out_img%.png}")"
      python "$VIS_SCRIPT" --nodes "$node_csv" --edges "$edges_csv" --out "$out_img" --title "$title" || warn "Graph render failed: $title"
      ((count++)) || true
    done
    shopt -u nullglob
    if (( count == 0 )); then
      warn "No node/edges CSV pairs found in $GRAPHS_DIR"
    else
      info "Rendered $count graph(s) to $GRAPHS_DIR"
    fi
  else
    warn "Visualizer not found: $VIS_SCRIPT — skipping graph visualizations"
  fi
else
  warn "Graphs directory not found: $GRAPHS_DIR — skipping graph visualizations"
fi
