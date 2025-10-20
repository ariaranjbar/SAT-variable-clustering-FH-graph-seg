# Hash-based File Selection in bench_runner.py

## Overview
The `bench_runner.py` script now supports selecting specific benchmark files using their hash values from a provided meta.csv file.

## Usage

In your configuration JSON file, you can now specify an array of hashes in the `files` section:

```json
{
  "out_dir": "scripts/benchmarks/out",
  "bench_dir": "benchmarks",
  "files": {
    "hashes": [
      "00d1fe07ab948b348bb3fb423b1ef40d",
      "02066c116dbacc40ec5cca2067db26c0",
      "0265448c232e3a25aa5bcd29b1b14567"
    ]
  },
  "algorithms": [
    {
      "name": "segmentation",
      "parameters": {
        ...
      }
    }
  ]
}
```

## Behavior

### Priority Order
When selecting files, `bench_runner.py` uses the following priority:
1. **`hashes`** - If provided, selects specific files by hash (overrides both `count` and `reuse_csv`)
2. **`reuse_csv`** - If provided and no hashes, reuses files from existing CSV
3. **`count`** - If neither hashes nor reuse_csv provided, randomly selects N files

### Hash Resolution
- Hashes are looked up in the provided meta.csv
- The hash corresponds to the filename in the `filename` column
- Files in the benchmarks directory are named as `{hash}-{filename}` (e.g., `00d1fe07ab948b348bb3fb423b1ef40d-lec_mult_KvW_12x11.sanitized.cnf.xz`)
- The script will match files in either format:
  - `{hash}-{filename}` (standard format)
  - `{filename}` (for backward compatibility)
- If a hash is not found in the provided meta.csv, a warning is printed and that file is skipped
- If a filename is not found in the benchmarks directory, a warning is printed and that file is skipped

### Example meta.csv format
```csv
hash,filename,family,author
00d1fe07ab948b348bb3fb423b1ef40d,lec_mult_KvW_12x11.sanitized.cnf.xz,hardware-miter,kochemazov
02066c116dbacc40ec5cca2067db26c0,mrpp_4x4#12_12.cnf.xz,planning,surynek
```

## Error Handling
- If `hashes` is provided but is not a list, a `ConfigError` is raised
- Invalid hashes produce warnings but do not stop execution
- The script continues with the files that were successfully found

## Example Configuration Files
See `scripts/benchmarks/configs/segmentation_with_hashes_example.json` for a complete example.
