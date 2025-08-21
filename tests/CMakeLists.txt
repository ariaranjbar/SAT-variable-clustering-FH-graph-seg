cmake_minimum_required(VERSION 3.16)
project(thesis_calcs_tests LANGUAGES CXX)

include(CTest)

# Smoke tests for all algorithms

# cnf_info: run on sample
set(SAMPLE_CNF ${CMAKE_SOURCE_DIR}/algorithms/cnf_info/sample.cnf)
add_test(NAME cnf_info_runs COMMAND $<TARGET_FILE:cnf_info> ${SAMPLE_CNF})

# vig_info: opt mode and naive mode on sample, tiny settings
add_test(NAME vig_info_opt_runs COMMAND $<TARGET_FILE:vig_info> -i ${SAMPLE_CNF} --tau 3 --opt -t 1)
add_test(NAME vig_info_naive_runs COMMAND $<TARGET_FILE:vig_info> -i ${SAMPLE_CNF} --tau 3 --naive)

# vig_info: stdin path with tau=inf and threads>1
add_test(NAME vig_info_stdin_opt_inf COMMAND bash -c "cat '${SAMPLE_CNF}' | '$<TARGET_FILE:vig_info>' -i - --tau inf --opt -t 2")

# vig_info: bad input should fail (non-existent path)
add_test(NAME vig_info_bad_input_fails COMMAND $<TARGET_FILE:vig_info> -i /definitely/not/found.cnf --tau 3 --opt)
set_tests_properties(vig_info_bad_input_fails PROPERTIES WILL_FAIL TRUE)

# segmentation: opt mode and naive mode on sample
add_test(NAME segmentation_opt_runs COMMAND $<TARGET_FILE:segmentation> -i ${SAMPLE_CNF} --tau 3 --k 50.0 --opt -t 1)
add_test(NAME segmentation_naive_runs COMMAND $<TARGET_FILE:segmentation> -i ${SAMPLE_CNF} --tau 3 --k 50.0 --naive)

# segmentation: stdin path with tau=inf and threads>1
add_test(NAME segmentation_stdin_opt_inf COMMAND bash -c "cat '${SAMPLE_CNF}' | '$<TARGET_FILE:segmentation>' -i - --tau inf --k 50.0 --opt -t 2")

# segmentation: bad input should fail (non-existent path)
add_test(NAME segmentation_bad_input_fails COMMAND $<TARGET_FILE:segmentation> -i /definitely/not/found.cnf --tau 3 --k 50.0 --opt)
set_tests_properties(segmentation_bad_input_fails PROPERTIES WILL_FAIL TRUE)
