# CHANGELOG
# ---------
# v1.0 - 2026-09-23
#     - Prima versione. Tre target:
#         risk_engine       libreria statica con la logica di calcolo e il
#                           fetch dati (porting di risk_engine.py)
#         risk_engine_tests eseguibile di unit test (doctest)
#         risk_engine_gui   dashboard desktop (Dear ImGui + ImPlot + GLFW),
#                           porting "a schermo" di app.py (Streamlit)
#       Le dipendenze header/sorgente (nlohmann/json, doctest, GLFW, Dear
#       ImGui, ImPlot) sono scaricate automaticamente con FetchContent, così
#       non serve installarle a mano oltre a libcurl e a un compilatore
#       OpenGL/X11 funzionante. Doc FetchContent:
#       https://cmake.org/cmake/help/latest/module/FetchContent.html
cmake_minimum_required(VERSION 3.20)
project(RiskEngineCpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

include(FetchContent)
find_package(CURL REQUIRED)

FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
    GIT_SHALLOW TRUE
)
FetchContent_Declare(
    doctest
    GIT_REPOSITORY https://github.com/doctest/doctest.git
    GIT_TAG v2.4.11
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(nlohmann_json doctest)

# --------------------------------------------------------------------------
# Libreria core: motore di calcolo + fetch dati di mercato.
# --------------------------------------------------------------------------
add_library(risk_engine STATIC
    src/risk_engine.cpp
    src/market_data.cpp
)
target_include_directories(risk_engine PUBLIC include)
target_link_libraries(risk_engine PUBLIC nlohmann_json::nlohmann_json CURL::libcurl)

# --------------------------------------------------------------------------
# Unit test.
# --------------------------------------------------------------------------
add_executable(risk_engine_tests tests/test_risk_engine.cpp)
target_link_libraries(risk_engine_tests PRIVATE risk_engine doctest::doctest)

enable_testing()
add_test(NAME risk_engine_tests COMMAND risk_engine_tests)

# --------------------------------------------------------------------------
# GUI desktop (Dear ImGui + ImPlot + GLFW/OpenGL3), opzionale: se GLFW/OpenGL
# non sono disponibili nell'ambiente di build (es. un container headless
# senza librerie X11/OpenGL), configura comunque libreria e test, saltando
# solo la GUI. Imposta -DRISKENGINE_BUILD_GUI=OFF per disattivarla a mano.
# --------------------------------------------------------------------------
option(RISKENGINE_BUILD_GUI "Costruisci la dashboard desktop (richiede OpenGL/GLFW)" ON)

if(RISKENGINE_BUILD_GUI)
    find_package(OpenGL QUIET)
    if(NOT OpenGL_FOUND)
        message(WARNING "OpenGL non trovato: la GUI (risk_engine_gui) non verrà costruita. "
                         "Installa i pacchetti di sviluppo OpenGL/X11 e riconfigura, oppure "
                         "usa risk_engine_tests da riga di comando.")
        set(RISKENGINE_BUILD_GUI OFF)
    endif()
endif()

if(RISKENGINE_BUILD_GUI)
    FetchContent_Declare(
        glfw
        GIT_REPOSITORY https://github.com/glfw/glfw.git
        GIT_TAG 3.4
        GIT_SHALLOW TRUE
    )
    set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
    set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
    # Niente wayland-scanner nell'immagine di build: ci basta il backend X11.
    set(GLFW_BUILD_WAYLAND OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(glfw)

    FetchContent_Declare(
        imgui
        GIT_REPOSITORY https://github.com/ocornut/imgui.git
        GIT_TAG v1.91.5
        GIT_SHALLOW TRUE
    )
    FetchContent_Declare(
        implot
        GIT_REPOSITORY https://github.com/epezent/implot.git
        GIT_TAG v0.16
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(imgui implot)

    # Dear ImGui e ImPlot non forniscono un CMakeLists.txt di libreria alla
    # radice: li impacchettiamo qui a mano coi soli file/backends che usiamo
    # (GLFW + OpenGL3). Doc backend: https://github.com/ocornut/imgui/wiki/Getting-Started
    add_library(imgui STATIC
        ${imgui_SOURCE_DIR}/imgui.cpp
        ${imgui_SOURCE_DIR}/imgui_draw.cpp
        ${imgui_SOURCE_DIR}/imgui_tables.cpp
        ${imgui_SOURCE_DIR}/imgui_widgets.cpp
        ${imgui_SOURCE_DIR}/imgui_demo.cpp
        ${imgui_SOURCE_DIR}/backends/imgui_impl_glfw.cpp
        ${imgui_SOURCE_DIR}/backends/imgui_impl_opengl3.cpp
    )
    target_include_directories(imgui PUBLIC
        ${imgui_SOURCE_DIR}
        ${imgui_SOURCE_DIR}/backends
    )
    target_link_libraries(imgui PUBLIC glfw OpenGL::GL)

    add_library(implot STATIC
        ${implot_SOURCE_DIR}/implot.cpp
        ${implot_SOURCE_DIR}/implot_items.cpp
    )
    target_include_directories(implot PUBLIC ${implot_SOURCE_DIR})
    target_link_libraries(implot PUBLIC imgui)

    add_executable(risk_engine_gui src/main.cpp)
    target_link_libraries(risk_engine_gui PRIVATE risk_engine imgui implot)
endif()
