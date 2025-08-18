cmake_minimum_required(VERSION 3.16)

project(thesis_calcs LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# macOS-specific fixes for finding standard library headers
if(APPLE)
    # Get the SDK path
    execute_process(COMMAND xcrun --show-sdk-path 
                    OUTPUT_VARIABLE MACOS_SDK_PATH 
                    OUTPUT_STRIP_TRAILING_WHITESPACE)
    
    # Add system include paths explicitly
    include_directories(SYSTEM 
        "${MACOS_SDK_PATH}/usr/include/c++/v1"
        "${MACOS_SDK_PATH}/usr/include"
    )
    
    # Set the sysroot
    set(CMAKE_OSX_SYSROOT ${MACOS_SDK_PATH})
endif()

option(THESIS_ENABLE_IPO "Enable interprocedural optimization if supported" ON)
include(CheckIPOSupported)
if(THESIS_ENABLE_IPO)
  check_ipo_supported(RESULT ipo_supported OUTPUT ipo_msg)
  if(ipo_supported)
    set(CMAKE_INTERPROCEDURAL_OPTIMIZATION ON)
  else()
    message(STATUS "IPO/LTO not supported: ${ipo_msg}")
  endif()
endif()

# Common library (shared include + optional sources)
add_library(thesis_common STATIC
  src/common/timer.cpp
  src/common/cli.cpp
  src/common/vig.cpp
)
add_library(thesis::common ALIAS thesis_common)

target_include_directories(thesis_common PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

target_compile_features(thesis_common PUBLIC cxx_std_20)

# Algorithms live under the algorithms/ folder
add_subdirectory(algorithms)

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tests/CMakeLists.txt)
  enable_testing()
  add_subdirectory(tests)
endif()
