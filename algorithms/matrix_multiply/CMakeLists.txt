cmake_minimum_required(VERSION 3.16)

add_executable(matrix_multiply
  main.cpp
)

set_target_properties(matrix_multiply PROPERTIES OUTPUT_NAME "matrix_multiply")

target_link_libraries(matrix_multiply PRIVATE thesis::common)

target_compile_features(matrix_multiply PRIVATE cxx_std_20)
