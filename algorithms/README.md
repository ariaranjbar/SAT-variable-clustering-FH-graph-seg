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
