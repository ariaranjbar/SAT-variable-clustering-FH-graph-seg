# cnf_info

Prints basic information about a DIMACS CNF file. Uses a lightweight parser with optional variable compaction and clause normalization.

## Usage

- New style (preferred):
  - `cnf_info --input <file.cnf|-> [--no-compact] [--no-normalize]`
- Legacy (still supported):
  - `cnf_info <file.cnf|-> [no-compact]`

Notes:

- `--input -` reads from stdin.
- `--no-compact` disables variable compaction during parsing.
- `--no-normalize` disables clause normalization (sort/dedup/tautology removal).

## Example

```bash
cnf_info --input algorithms/cnf_info/sample.cnf
cnf_info --input - --no-compact --no-normalize < algorithms/cnf_info/sample.cnf
```
