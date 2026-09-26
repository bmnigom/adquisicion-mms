# -*- mode: python ; coding: utf-8 -*-
# Ejecutable de Adquisicion MMS (carpeta con AdquisicionMMS.exe y sus dependencias).
# Construir con:  packaging\construir.cmd   (o: pyinstaller packaging\MMS.spec)
import os

import mbientlab.metawear
import mbientlab.warble

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Las bibliotecas nativas de MetaWear y Warble (Bluetooth) se cargan con una ruta
# relativa al propio modulo, asi que deben quedar en la misma carpeta que su __init__.
native = [
    (os.path.join(os.path.dirname(mbientlab.metawear.__file__), "MetaWear.Win32.dll"), "mbientlab/metawear"),
    (os.path.join(os.path.dirname(mbientlab.warble.__file__), "warble.dll"), "mbientlab/warble"),
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=native,
    datas=[(os.path.join(ROOT, "LEEME.md"), "."), (os.path.join(ROOT, "packaging", "mms.png"), ".")],
    hiddenimports=["mbientlab.metawear", "mbientlab.metawear.cbindings", "mbientlab.warble"],
    excludes=["pandas", "matplotlib", "scipy", "tkinter", "IPython", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AdquisicionMMS",
    console=False,
    icon=os.path.join(ROOT, "packaging", "mms.ico"),
    version=os.path.join(ROOT, "packaging", "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="AdquisicionMMS")
