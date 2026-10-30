cmake_minimum_required(VERSION 3.16)
project(FlashKV VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Optimization flags
if (MSVC)
    add_compile_options(/W4 /O2)
else()
    add_compile_options(-Wall -Wextra -O3 -pthread)
endif()

if (WIN32 AND NOT MSVC)
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -static -static-libgcc -static-libstdc++")
endif()

# Core library sources
set(FLASHKV_CORE_SRCS
    01_core_cpp_engine/engine/DoublyLinkedList.cpp
    01_core_cpp_engine/engine/LRUCache.cpp
    01_core_cpp_engine/engine/StorageEngine.cpp
    01_core_cpp_engine/protocol/CommandParser.cpp
    01_core_cpp_engine/concurrency/ThreadPool.cpp
    01_core_cpp_engine/persistence/AOFManager.cpp
    01_core_cpp_engine/server/TcpServer.cpp
)

include_directories(01_core_cpp_engine)

# Server Executable
add_executable(flashkv_server 01_core_cpp_engine/main.cpp ${FLASHKV_CORE_SRCS})

# Interactive CLI Client
add_executable(flashkv_client 03_cli_client/FlashKVClient.cpp)

# Benchmark Tool
add_executable(flashkv_benchmark 04_benchmark_suite/BenchmarkTool.cpp)

# Unit Tests Executable
add_executable(flashkv_tests 05_unit_tests/UnitTests.cpp ${FLASHKV_CORE_SRCS})

# Link libraries (Winsock for Windows, pthreads for Linux)
if (WIN32)
    target_link_libraries(flashkv_server PRIVATE ws2_32)
    target_link_libraries(flashkv_client PRIVATE ws2_32)
    target_link_libraries(flashkv_benchmark PRIVATE ws2_32)
    target_link_libraries(flashkv_tests PRIVATE ws2_32)
else()
    target_link_libraries(flashkv_server PRIVATE pthread)
    target_link_libraries(flashkv_client PRIVATE pthread)
    target_link_libraries(flashkv_benchmark PRIVATE pthread)
    target_link_libraries(flashkv_tests PRIVATE pthread)
endif()
