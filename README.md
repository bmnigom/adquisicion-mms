# Adquisición MMS

Aplicación de escritorio (Windows) para registrar movimiento con un sensor inercial MetaWear (MMS) por Bluetooth y realizar pruebas funcionales: salto vertical, sit-to-stand, golpe rápido, TUG, marcha de 5 m, bipedestación y apoyo monopodal. Tras cada intento muestra un **reporte para el personal** con veredicto de validez, resultados, interpretación y calidad de la medición.

## Instalar en otro computador

1. Descargue `AdquisicionMMS-<versión>-instalador.exe` desde la sección **Releases** de este repositorio.
2. Ejecútelo (no requiere permisos de administrador). Si Windows SmartScreen avisa «Windows protegió su PC», elija **Más información → Ejecutar de todas formas**: el instalador no está firmado digitalmente.
3. Abra **Adquisición MMS** desde el menú Inicio, encienda el sensor y pulse **Configurar sensor → Buscar sensores** para asignar el sensor de ese equipo.

Requisitos: Windows 10 u 11 de 64 bits con Bluetooth de baja energía (4.0 o superior). Los datos y reportes se guardan en `%LOCALAPPDATA%\AdquisicionMMS\data` y no se borran al desinstalar.

El manual de uso (protocolo de campo, cómo leer el reporte, cambios de la versión 2) está en [LEEME.md](LEEME.md).

## Desarrollo

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python main.py --simulate      :: interfaz con datos sintéticos, sin sensor
.venv\Scripts\python -m tests.test_algoritmos :: pruebas de los algoritmos
```

Construir el ejecutable y el instalador (requiere [Inno Setup 6](https://jrsoftware.org/isinfo.php)):

```bat
packaging\construir.cmd
```

Genera `dist\AdquisicionMMS\` (ejecutable) y `dist\instalador\AdquisicionMMS-<versión>-instalador.exe`. Para una nueva versión, actualice el número en `core/__init__.py`, `packaging/instalador.iss` y `packaging/version_info.txt`.

Los datos de participantes (`data/`) no se versionan.
