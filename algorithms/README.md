# Guidelines for adding new algorithms

1. Create a folder: `algorithms/<your_algo>`
2. Add a `CMakeLists.txt` similar to others:

   add_executable(<your_algo>
     main.cpp
   )
   target_link_libraries(<your_algo> PRIVATE thesis::common)
   target_compile_features(<your_algo> PRIVATE cxx_std_20)

3. Implement a small `main.cpp` that accepts minimal CLI args and prints results and timing.
   - Use `thesis::ArgParser` for consistent flags.
   - Print a single summary line on stdout with `key=value` pairs (order-agnostic).
     Required keys if you want to integrate with the Python runner should be listed in your registry entry (see below).
4. Reconfigure/build to produce the binary.

## Registering in the benchmark runner

Add an entry to `scripts/benchmarks/configs/algorithms.json` to make your tool available as a subcommand of the Python runner. Define:

- `discover`: relative paths to find your built binary.
- `cmd_template`: how to invoke it; use `${input}` for the file (runner streams `.xz` inputs via stdin so `${input}` becomes `-`).
- `params`: schema for CLI-exposed sweeps (types, defaults, validation, conditions).
- `csv`: output CSV path/header and `required_keys` the runner must parse from your stdout.

See existing entries (`vig_info`, `segmentation`, `cnf_info`) for a template.
