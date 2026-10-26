@echo off
setlocal
if "%~1"=="" (
  echo Usage: start-companion.cmd YOUR_WORKSTATION_PRIVATE_IPV4
  echo Example: start-companion.cmd 192.168.1.50
  echo The server never starts without an explicit bind address.
  exit /b 2
)
set "PYTHONPATH=%~dp0SideTap\src;%PYTHONPATH%"
set "PATH=W:\Toolchains\JS\npm-global;%PATH%"
if defined SIDETAP_PYTHON_EXE (
  "%SIDETAP_PYTHON_EXE%" -m phone_harness companion --bind "%~1"
) else (
  "W:\Dev\SideTap\.venv\Scripts\python.exe" -m phone_harness companion --bind "%~1"
)
