cmake_minimum_required(VERSION 3.24)
project(ccsds_gs LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# CLAUDE.md §5.3: warnings are errors; sanitizers in Debug.
add_compile_options(-Wall -Wextra -Werror -Wconversion -Wshadow)
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
  add_link_options(-fsanitize=address,undefined)
endif()

add_library(gs_core src/iq_replay.cpp)
target_include_directories(gs_core PUBLIC include)

add_executable(gs-replay src/gs_replay_main.cpp)
target_link_libraries(gs-replay PRIVATE gs_core)

# GoogleTest pinned by tag and hash (docs/toolchain.md).
include(FetchContent)
FetchContent_Declare(googletest
  URL https://github.com/google/googletest/releases/download/v1.15.2/googletest-1.15.2.tar.gz
  URL_HASH SHA256=7b42b4d6ed48810c5362c265a17faebe90dc2373c885e5216439d37927f02926
  DOWNLOAD_EXTRACT_TIMESTAMP ON)
set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)
# Third-party code is not held to our -Werror flags.
foreach(t gtest gtest_main gmock gmock_main)
  if(TARGET ${t})
    target_compile_options(${t} PRIVATE -w)
  endif()
endforeach()

enable_testing()
add_executable(gs_tests tests/iq_replay_test.cpp)
target_link_libraries(gs_tests PRIVATE gs_core GTest::gtest_main)
include(GoogleTest)
gtest_discover_tests(gs_tests)
