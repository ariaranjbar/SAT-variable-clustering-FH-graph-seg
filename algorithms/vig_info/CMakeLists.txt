cmake_minimum_required(VERSION 3.16)

add_executable(vig_info
  main.cpp
)

set_target_properties(vig_info PROPERTIES OUTPUT_NAME "vig_info")

target_link_libraries(vig_info PRIVATE thesis::common)

target_compile_features(vig_info PRIVATE cxx_std_20)
