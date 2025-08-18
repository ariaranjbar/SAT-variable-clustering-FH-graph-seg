cmake_minimum_required(VERSION 3.16)
project(thesis_calcs_tests LANGUAGES CXX)

include(CTest)

# A tiny smoke test that builds both example algorithms
add_test(NAME matrix_multiply_runs COMMAND matrix_multiply 64)
add_test(NAME prime_sieve_runs COMMAND prime_sieve 1000000)
