#!/usr/bin/env bash
set -euo pipefail

# Create/Update a conda env and run plotting
ENV_NAME="thesis-bench"
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$THIS_DIR/../.." && pwd)"
CSV_PATH="$ROOT_DIR/scripts/benchmarks/out/results.csv"
OUT_DIR="$ROOT_DIR/scripts/benchmarks/out/plots"
CONDARC_FILE="$ROOT_DIR/.condarc"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is not on PATH. Please install Miniconda/Anaconda and ensure 'conda' is available."
  exit 1
fi

# Prefer project-local condarc to avoid implicit defaults warnings
if [[ -f "$CONDARC_FILE" ]]; then
  export CONDARC="$CONDARC_FILE"
fi

# Flags
DO_UPDATE=0
if [[ ${1:-} == "--update" ]]; then
  DO_UPDATE=1
fi

# Ensure env exists
if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Using existing conda env: $ENV_NAME"
  if [[ $DO_UPDATE -eq 1 ]]; then
    echo "Updating conda env from environment.yml (requested via --update)"
    # Try to update, but don't abort if conda crashes; continue with best-effort
    set +e
    conda env update -n "$ENV_NAME" -f "$THIS_DIR/environment.yml"
    UPDATE_RC=$?
    set -e
    if [[ $UPDATE_RC -ne 0 ]]; then
      echo "Warning: 'conda env update' failed (rc=$UPDATE_RC). Proceeding without update."
    fi
  else
    echo "Skipping env update (pass --update to update from environment.yml)"
  fi
else
  echo "Creating conda env: $ENV_NAME"
  # Create from environment.yml; if that fails, fall back to minimal create and install deps
  set +e
  conda env create -f "$THIS_DIR/environment.yml"
  CREATE_RC=$?
  set -e
  if [[ $CREATE_RC -ne 0 ]]; then
    echo "Fallback: creating minimal env and installing dependencies"
    conda create -y -n "$ENV_NAME" python=3.10
    conda install -y -n "$ENV_NAME" -c conda-forge pandas numpy matplotlib seaborn || true
  fi
fi

# Ensure required packages are present; install if missing
set +e
conda run -n "$ENV_NAME" python - <<'PY'
import importlib, sys
mods = ["pandas", "numpy", "matplotlib", "seaborn"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
sys.exit(1 if missing else 0)
PY
NEED_INSTALL=$?
set -e
if [[ $NEED_INSTALL -ne 0 ]]; then
  echo "Installing missing Python packages into $ENV_NAME"
  conda install -y -n "$ENV_NAME" -c conda-forge pandas numpy matplotlib seaborn || true
fi

# Run plotter via conda run
mkdir -p "$OUT_DIR"
conda run -n "$ENV_NAME" python "$THIS_DIR/plot_results.py" --csv "$CSV_PATH" --outdir "$OUT_DIR"

echo "Plots written to $OUT_DIR"
