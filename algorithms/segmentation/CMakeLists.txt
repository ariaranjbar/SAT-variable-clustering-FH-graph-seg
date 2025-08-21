cmake_minimum_required(VERSION 3.16)

add_executable(segmentation
  main.cpp
)

set_target_properties(segmentation PROPERTIES OUTPUT_NAME "segmentation")

target_link_libraries(segmentation PRIVATE thesis::common)

target_compile_features(segmentation PRIVATE cxx_std_20)
