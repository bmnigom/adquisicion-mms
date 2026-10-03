@echo off
setlocal
set "APP_DIR=%~dp0"
if not exist "%APP_DIR%main.py" (
    echo No se encontro main.py junto a este iniciador.
    echo Si abrio el archivo desde el ZIP, cierre esta ventana y elija "Extraer todo".
    echo Despues abra la carpeta extraida y ejecute Simular_MMS.cmd o Iniciar_MMS.cmd.
    pause
    exit /b 1
)
if defined APP_PYTHON goto :run
if exist "%APP_DIR%.venv\Scripts\python.exe" (
    set "APP_PYTHON=%APP_DIR%.venv\Scripts\python.exe"
) else (
    set "APP_PYTHON=python"
)
:run
pushd "%APP_DIR%"
"%APP_PYTHON%" -X utf8 "%APP_DIR%main.py" %*
set "APP_EXIT=%ERRORLEVEL%"
popd
if not "%APP_EXIT%"=="0" (
    echo.
    echo MMS no pudo iniciarse. El mensaje de error aparece arriba.
    pause
)
exit /b %APP_EXIT%
