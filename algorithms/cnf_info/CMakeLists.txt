cmake_minimum_required(VERSION 3.16)

add_executable(cnf_info
  main.cpp
)

set_target_properties(cnf_info PROPERTIES OUTPUT_NAME "cnf_info")

target_link_libraries(cnf_info PRIVATE thesis::common)

target_compile_features(cnf_info PRIVATE cxx_std_20)
