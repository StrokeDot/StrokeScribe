cmake_minimum_required(VERSION 3.16)
project(StrokeScribeOfx CXX)
# Build:  cmake -S ofx -B build -DOFX_INCLUDE=<openfx>/include -DSTB_DIR=<stb>
#         cmake --build build --config Release
set(CMAKE_CXX_STANDARD 17)
set(OFX_INCLUDE "" CACHE PATH "openfx/include folder")
set(STB_DIR "" CACHE PATH "stb folder")
find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(HAND_HEADER ${CMAKE_CURRENT_BINARY_DIR}/hand_png.h)
add_custom_command(OUTPUT ${HAND_HEADER}
  COMMAND Python3::Interpreter ${CMAKE_CURRENT_SOURCE_DIR}/tools/embed.py
          ${CMAKE_CURRENT_SOURCE_DIR}/../assets/default_hand.png ${HAND_HEADER} kHandPng
  DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/../assets/default_hand.png ${CMAKE_CURRENT_SOURCE_DIR}/tools/embed.py)

add_library(StrokeScribeTest MODULE src/strokescribe_test.cpp ${HAND_HEADER})
target_include_directories(StrokeScribeTest PRIVATE ${OFX_INCLUDE} ${STB_DIR} ${CMAKE_CURRENT_BINARY_DIR})
set_target_properties(StrokeScribeTest PROPERTIES PREFIX "" SUFFIX ".ofx")
if(MSVC)
  # Static runtime: no Visual C++ redistributable needed on the user's PC.
  set_property(TARGET StrokeScribeTest PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
  target_compile_options(StrokeScribeTest PRIVATE /EHsc /W3)
  target_compile_definitions(StrokeScribeTest PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
endif()

add_executable(ofx_test_host tools/test_host.cpp)
target_include_directories(ofx_test_host PRIVATE ${OFX_INCLUDE} ${STB_DIR})
if(MSVC)
  set_property(TARGET ofx_test_host PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
  target_compile_definitions(ofx_test_host PRIVATE _CRT_SECURE_NO_WARNINGS NOMINMAX)
else()
  target_link_libraries(ofx_test_host PRIVATE ${CMAKE_DL_LIBS})
endif()
