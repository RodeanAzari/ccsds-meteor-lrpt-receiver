cmake_minimum_required(VERSION 3.24)
project(ccsds_gs LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# CLAUDE.md §5.3: warnings are errors; sanitizers in Debug.
add_compile_options(-Wall -Wextra -Werror -Wconversion -Wshadow)
# GS_TSAN: ThreadSanitizer instead (it cannot be combined with ASan): the SPSC ring's threaded test (make gs-test).
option(GS_TSAN "Build with ThreadSanitizer" OFF)
if(GS_TSAN)
  add_compile_options(-fsanitize=thread -fno-omit-frame-pointer)
  add_link_options(-fsanitize=thread)
elseif(CMAKE_BUILD_TYPE STREQUAL "Debug")
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all)
  add_link_options(-fsanitize=address,undefined)
endif()
find_package(Threads REQUIRED)

add_library(gs_core src/iq_replay.cpp src/board_packets.cpp src/cadu_diff.cpp src/view.cpp)
target_include_directories(gs_core PUBLIC include)

add_executable(gs-replay src/gs_replay_main.cpp)
target_link_libraries(gs-replay PRIVATE gs_core)

add_executable(gs-rx src/gs_rx_main.cpp)
target_link_libraries(gs-rx PRIVATE gs_core Threads::Threads)

add_executable(gs-diff src/gs_diff_main.cpp)
target_link_libraries(gs-diff PRIVATE gs_core)

add_executable(gs-view src/gs_view_main.cpp)
target_link_libraries(gs-view PRIVATE gs_core)

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
add_executable(gs_tests tests/iq_replay_test.cpp tests/board_packets_test.cpp tests/space_packets_test.cpp
                        tests/spsc_ring_test.cpp tests/cadu_diff_test.cpp
                        tests/status_test.cpp tests/view_test.cpp)
target_link_libraries(gs_tests PRIVATE gs_core GTest::gtest_main Threads::Threads)
# Packets the RTL sent in simulation (tb/cocotb/test_arty_rx_eth_top_full.py, CAPTURE_DIR): read by board_packets_test.
target_compile_definitions(gs_tests PRIVATE GS_TEST_DATA_DIR="${CMAKE_CURRENT_SOURCE_DIR}/tests/data")
include(GoogleTest)
gtest_discover_tests(gs_tests)

# libFuzzer target (make fuzz): clang only, with ASan and UBSan.
option(GS_FUZZ "Build the libFuzzer targets (needs clang)" OFF)
if(GS_FUZZ)
  add_executable(board_packets_fuzz fuzz/board_packets_fuzz.cpp src/board_packets.cpp)
  target_include_directories(board_packets_fuzz PRIVATE include)
  target_compile_options(board_packets_fuzz PRIVATE -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all)
  target_link_options(board_packets_fuzz PRIVATE -fsanitize=fuzzer,address,undefined)
  add_executable(space_packets_fuzz fuzz/space_packets_fuzz.cpp)
  target_include_directories(space_packets_fuzz PRIVATE include)
  target_compile_options(space_packets_fuzz PRIVATE -fsanitize=fuzzer,address,undefined -fno-sanitize-recover=all)
  target_link_options(space_packets_fuzz PRIVATE -fsanitize=fuzzer,address,undefined)
endif()
