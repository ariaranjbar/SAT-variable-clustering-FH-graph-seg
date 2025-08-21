# Guidelines for adding new algorithms

1. Create a folder: `algorithms/<your_algo>`
2. Add a `CMakeLists.txt` similar to others:

   add_executable(<your_algo>
     main.cpp
   )
   target_link_libraries(<your_algo> PRIVATE thesis::common)
   target_compile_features(<your_algo> PRIVATE cxx_std_20)

3. Implement a small `main.cpp` that accepts minimal CLI args and prints results and timing.
4. Reconfigure/build to produce the binary.

## Registering in the benchmark runner

Add an entry to `scripts/benchmarks/configs/algorithms.json` to make your tool available as a subcommand of the Python runner. Define binary discovery hints, the command template, parameter schema (with validation), and CSV mapping. See existing entries (e.g., `vig_info`, `segmentation`) for a template.
