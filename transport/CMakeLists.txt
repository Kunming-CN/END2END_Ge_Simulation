cmake_minimum_required(VERSION 3.28)
get_filename_component(PROJECT_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.." ABSOLUTE)
file(RELATIVE_PATH BUILD_RELATIVE "${PROJECT_ROOT}/.local/m2a" "${CMAKE_BINARY_DIR}")
if(BUILD_RELATIVE MATCHES "^\\.\\." OR IS_ABSOLUTE "${BUILD_RELATIVE}")
  message(FATAL_ERROR "Build under project .local/m2a, never in the source directory")
endif()

project(m2a_geometry_probe LANGUAGES CXX)
# This project is only the original, small GDML inspection utility.
find_package(Geant4 REQUIRED gdml)
include(${Geant4_USE_FILE})
add_executable(geometry_probe geometry_probe.cc)
target_compile_features(geometry_probe PRIVATE cxx_std_17)
target_link_libraries(geometry_probe PRIVATE ${Geant4_LIBRARIES})
target_compile_definitions(geometry_probe PRIVATE PROJECT_LOCAL="${PROJECT_ROOT}/.local")

# Separate nominal Cs137 assembly exporter; the original probe is unchanged.
add_executable(cryostat_export cryostat_export.cc)
target_compile_features(cryostat_export PRIVATE cxx_std_17)
target_link_libraries(cryostat_export PRIVATE ${Geant4_LIBRARIES})
target_compile_definitions(cryostat_export PRIVATE PROJECT_LOCAL="${PROJECT_ROOT}/.local")
