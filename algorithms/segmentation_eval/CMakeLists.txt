cmake_minimum_required(VERSION 3.16)

add_executable(segmentation_eval
  main.cpp
)

set_target_properties(segmentation_eval PROPERTIES OUTPUT_NAME "segmentation_eval")

target_link_libraries(segmentation_eval PRIVATE thesis::common)

target_compile_features(segmentation_eval PRIVATE cxx_std_20)
