@echo off
setlocal
rem Use the pinned, real SideTap source vendored into the LiveContainer fork.
set "PYTHONPATH=%~dp0SideTap\src;%PYTHONPATH%"
set "PATH=W:\Toolchains\JS\npm-global;%PATH%"
if defined SIDETAP_PYTHON_EXE (
  "%SIDETAP_PYTHON_EXE%" -m phone_harness mcp
) else (
  "W:\Dev\SideTap\.venv\Scripts\python.exe" -m phone_harness mcp
)
