cmake_minimum_required(VERSION 3.16)

add_executable(louvain
  main.cpp
)

set_target_properties(louvain PROPERTIES OUTPUT_NAME "louvain")

target_link_libraries(louvain PRIVATE thesis::common)

# Follow project convention: C++20

target_compile_features(louvain PRIVATE cxx_std_20)
