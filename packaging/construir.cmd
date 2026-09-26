@echo off
rem Construye el ejecutable (dist\AdquisicionMMS) y, si Inno Setup esta instalado, el instalador.
setlocal
set "ROOT=%~dp0.."
set "APP_PYTHON=C:\Users\fx517\miniconda3\envs\adquisicion-mms\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=python"
pushd "%ROOT%"
"%APP_PYTHON%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\MMS.spec || goto :error
start "" /wait dist\AdquisicionMMS\AdquisicionMMS.exe --check
if errorlevel 1 goto :error
set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" packaging\instalador.iss || goto :error
) else (
    echo Inno Setup no esta instalado: se omite el instalador. Ejecutable en dist\AdquisicionMMS
)
popd
exit /b 0
:error
popd
echo La construccion fallo.
exit /b 1
