# cnf_info

Prints basic information about a DIMACS CNF file and previews the first few clauses.

## Usage

- New style (preferred):
  - `cnf_info --input <file.cnf|-> [--no-compact]`
- Legacy (still supported):
  - `cnf_info <file.cnf|-> [no-compact]`

Notes:

- `--input -` reads from stdin.
- `--no-compact` disables variable compaction during parsing.

## Example

```bash
cnf_info --input algorithms/cnf_info/sample.cnf
```
