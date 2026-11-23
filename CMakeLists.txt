cmake_minimum_required(VERSION 3.20)
project(sat-solver LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

add_library(satcore STATIC
  src/dimacs.cpp
  src/generators.cpp
  src/heuristics.cpp
  src/solver.cpp
)
target_include_directories(satcore PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(satcore PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(satsolver src/satsolver_main.cpp)
target_link_libraries(satsolver PRIVATE satcore)

add_executable(satgen src/satgen_main.cpp)
target_link_libraries(satgen PRIVATE satcore)

enable_testing()
add_executable(sat_tests tests/test_solver.cpp)
target_link_libraries(sat_tests PRIVATE satcore)
add_test(NAME sat_tests COMMAND sat_tests)
