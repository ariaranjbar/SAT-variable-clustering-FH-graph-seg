# Contributing

- Keep shared code in `include/thesis` and `src/common`.
- Add new algorithms under `algorithms/<name>/` with a `CMakeLists.txt` and a `main.cpp`.
- Link against `thesis::common` to use shared headers/utilities.
- Prefer modern C++ (C++20). Avoid heavy dependencies unless justified.
