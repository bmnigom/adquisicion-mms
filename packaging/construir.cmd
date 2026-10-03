@echo off
rem Construye el ejecutable (dist\AdquisicionMMS) y, si Inno Setup esta instalado, el instalador.
setlocal
set "APP_DIR=%~dp0..\"
if defined APP_PYTHON goto :run
if exist "%APP_DIR%.venv\Scripts\python.exe" (
    set "APP_PYTHON=%APP_DIR%.venv\Scripts\python.exe"
) else (
    set "APP_PYTHON=python"
)
:run
pushd "%APP_DIR%"
"%APP_PYTHON%" -X utf8 packaging\build.py %*
set "APP_EXIT=%ERRORLEVEL%"
popd
exit /b %APP_EXIT%
