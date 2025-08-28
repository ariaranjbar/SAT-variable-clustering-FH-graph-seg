# Config-driven benchmark runner (minimal overrides)

This folder contains JSON/YAML configuration files for `bench_runner.py config --file <path>`.

## Why configs?

- Decouple algorithm definitions from the runner.
- Express complex parameter relations (e.g., sweep threads only when impl=opt).
- Mirror existing behavior for `vig_info` and `segmentation` while staying extensible.

## Schema overview

Top-level fields:

- `out_dir`: Where CSVs/logs are written. Default: `scripts/benchmarks/out`.
- `bench_dir`: Where CNF inputs live. Default: `benchmarks`.
- `files`: How to choose input files:
  - `count`: number of random files to pick.
  - `reuse_csv`: optional path to reuse the file list from an existing CSV (ignores `count`).
- `algorithms`: list of algorithm blocks.

Algorithm block (minimal):

- `name` (required): algorithm name (must exist in `configs/algorithms.json`).
- `parameters` (optional): mapping of parameter name -> list of values to sweep. Omitted params use the registry defaults and conditions.
- `skip_existing` (optional): bool. Uses registry’s `csv.key_cols`.
- Advanced (optional overrides):
  - `bin`: explicit path to the binary (else runner uses registry discovery).
  - `discover`: extra binary paths to try before fallback.
  - `base_params`, `cmd_template`, `csv`: only needed if you want to diverge from the registry schema.

Notes:

- Validation (enums, numeric ranges, allow_inf) comes from the registry schema and applies to overrides.
- Streaming vs file input: if input ends with `.xz`, `${input}` becomes `-` and decompression is piped.
- Per-file caching: enabled by default; set `cache: false` in the algorithm block to disable.

## Example

See `example_configs.json` for a minimal ready-to-run configuration.

Run it:

```bash
scripts/benchmarks/bench_runner.py config --file scripts/benchmarks/configs/example_configs.json -v
```

## CSV mapping

- The runner parses key=value summary lines from stdout (order-agnostic) and maps to CSV columns by name.
- `file` and `memlimit_mb` are filled by the runner when present in the header; other columns should match keys produced by the algorithm.
- To enable skip-existing, choose `key_cols` that uniquely identify a combination (e.g., `file,impl,tau,threads,maxbuf`).

## Algorithms registry (define algorithms for direct CLI use)

Define algorithms once in `scripts/benchmarks/configs/algorithms.json` and they become first-class CLI subcommands. This avoids editing `bench_runner.py` when adding new tools.

Schema for each entry in `algorithms`:

- `name` (string): Subcommand name to use on CLI.
- `help` (string, optional): Help text for `-h`.
- `discover` (list of strings, optional): Relative paths to try for the binary (first executable wins). If omitted, the runner attempts built-in discovery by name.
- `cmd_template` (list of strings): Command tokens. Supported variables:
  - `${bin}`: replaced by discovered/explicit `--bin` path. If omitted, the runner prepends the binary path to the command.
  - `${input}`: `-` when streaming `.xz`, otherwise absolute file path.
  - `${param}`: replaced by values from `base_params`/`params` sweeps.
  - Unresolved placeholder pairs like `-t ${threads}` are automatically removed (useful when `threads` only applies for some `impl`).
- `base_params` (object): Default static params available to the template.
- `params` (list): Parameter schema used to auto-create CLI flags and generate sweeps:
  - `name`: logical parameter name (e.g., `impl`, `tau`, `threads`).
  - `cli`: CLI flag to accept values from the user (e.g., `--taus`, `--threads`). Values are comma-separated.
  - `type`: `string` | `int` | `float` (affects how values are parsed from CLI).
  - `default`: default values used if the CLI flag is not provided.
  - `when` (optional): condition object restricting when the param applies (see conditions above).
  - Validation: use fields like `enum`, `numeric: int|float`, `min`, `max`, and `allow_inf`. The runner enforces these for both CLI and config modes.
- `csv` (object): Output mapping identical to the config-driven runner: `path`, `header`, `required_keys`, `key_cols`.

Usage example after registering `vig_info_dyn`:

```bash
python scripts/benchmarks/bench_runner.py vig_info_dyn -n 3 \
  --implementations naive,opt --taus 3,5,10,inf --threads 1,2,4 --maxbufs 50000000,100000000 \
  --skip-existing -v
```
