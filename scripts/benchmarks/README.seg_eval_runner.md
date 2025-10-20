# segmentation_eval runner

A small, specialized runner around the `segmentation_eval` binary.
It reads a JSON config, samples input CNF files from a root directory, runs the binary once per file, and merges per-file CSVs into a single combined CSV.

- Supports `.cnf` and `.cnf.xz` inputs (the latter is decompressed automatically).
- Minimal dependencies (Python 3.8+ in macOS/Linux).
- Status is printed to stdout; errors to stderr. The `segmentation_eval` results are in CSV files.

## Config

See `scripts/benchmarks/segmentation_eval_config.sample.json` for a full example. Important fields:

- root_dir: directory containing CNF files (can be the repo `benchmarks/`).
- recursive: whether to search recursively (true/false).
- sample_count: number of files to randomly sample.
- bin: path to the built `segmentation_eval` binary.
- out_dir: directory for per-file CSVs.
- combined_csv: path for the merged CSV.
- impl: "opt" or "naive".
- threads, maxbuf: optional builder knobs used by the optimized builder.
- tau, k, size_exp, mod_guard, gamma, anneal, dq_tol0, dq_vscale, ambiguous, gate_margin: passed through to the binary as-is (comma-separated lists supported, handled by the binary).

## Run

```bash
python scripts/benchmarks/segmentation_eval_runner.py scripts/benchmarks/configs/segmentation_eval_config.sample.json
```

## What it does

- Picks `sample_count` random files under `root_dir`.
- For each file, creates a per-file CSV named `<stem>__seg_eval.csv` in `out_dir`, appends it into `combined_csv`, then deletes the per-file CSV.
- Only the `combined_csv` remains at the end, and instead of full file paths it contains a numeric `file_id` column. The mapping of `file_id` to full path is written to `file_map.csv` in the same `out_dir`.
