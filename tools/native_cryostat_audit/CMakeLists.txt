cmake_minimum_required(VERSION 3.20)

# This isolated target must never reuse an old campaign or an in-source build.
get_filename_component(AUDIT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
file(REAL_PATH "${AUDIT_ROOT}" AUDIT_ROOT_REAL)
file(REAL_PATH "${CMAKE_CURRENT_LIST_DIR}" AUDIT_SOURCE_REAL)
file(REAL_PATH "${CMAKE_BINARY_DIR}" AUDIT_BINARY_REAL)
set(AUDIT_BUILD "${AUDIT_ROOT}/.local/m11f-cryostat-native-v1/build")
if(NOT AUDIT_ROOT STREQUAL AUDIT_ROOT_REAL
   OR NOT CMAKE_CURRENT_LIST_DIR STREQUAL AUDIT_SOURCE_REAL
   OR NOT CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_CURRENT_LIST_DIR
   OR NOT CMAKE_BINARY_DIR STREQUAL AUDIT_BUILD
   OR NOT AUDIT_BINARY_REAL STREQUAL AUDIT_BUILD)
  message(FATAL_ERROR "Only the unlinked .local/m11f-cryostat-native-v1/build directory is allowed")
endif()

project(cryostat_native_audit LANGUAGES CXX)
find_package(Geant4 11.3.2 EXACT REQUIRED)
include(${Geant4_USE_FILE})
add_executable(cryostat_native_audit audit.cc)
target_compile_features(cryostat_native_audit PRIVATE cxx_std_17)
set_target_properties(cryostat_native_audit PROPERTIES CXX_EXTENSIONS OFF)
target_compile_definitions(cryostat_native_audit PRIVATE AUDIT_PROJECT_ROOT="${AUDIT_ROOT}")
target_link_libraries(cryostat_native_audit PRIVATE ${Geant4_LIBRARIES})
