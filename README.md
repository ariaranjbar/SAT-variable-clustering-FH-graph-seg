# Thesis Calculations (CMake C++ project)

This repository organizes algorithmic binaries for a thesis.

Layout
- include/thesis/    -> shared headers used by all algorithms
- src/common/        -> shared implementations compiled into a static lib (thesis_common)
- algorithms/        -> each subfolder is a standalone binary with its own main()

Build (Windows PowerShell)
1. Configure and build:
   - mkdir build
   - cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
   - cmake --build build --config Release

2. Binaries will be under build/algorithms/<name>/ (on multi-config generators) or build/ (single-config).
