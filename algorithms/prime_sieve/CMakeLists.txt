cmake_minimum_required(VERSION 3.16)

add_executable(prime_sieve
  main.cpp
)

set_target_properties(prime_sieve PROPERTIES OUTPUT_NAME "prime_sieve")

target_link_libraries(prime_sieve PRIVATE thesis::common)

target_compile_features(prime_sieve PRIVATE cxx_std_20)
