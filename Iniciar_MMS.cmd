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
set "APP_PYTHON=C:\Users\fx517\miniconda3\envs\adquisicion-mms\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%APP_DIR%.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%APP_DIR%env\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
    echo No se encontro Python para MMS.
    echo Instale las dependencias indicadas en LEEME.md.
    pause
    exit /b 1
)
pushd "%APP_DIR%"
"%APP_PYTHON%" "%APP_DIR%main.py" %*
set "APP_EXIT=%ERRORLEVEL%"
popd
if not "%APP_EXIT%"=="0" (
    echo.
    echo MMS no pudo iniciarse. El mensaje de error aparece arriba.
    pause
)
exit /b %APP_EXIT%
