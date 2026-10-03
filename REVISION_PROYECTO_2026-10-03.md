# Revisión de Adquisición MMS

Fecha: 3 de octubre de 2026. Alcance: código, documentación, pruebas y configuración de entrega disponibles en este repositorio. Se hicieron tres revisiones paralelas: algoritmos, Bluetooth/interfaz y datos/empaquetado. No se modificó código de la aplicación ni se leyeron mediciones de participantes.

La estructura `core/` y `ui/`, el simulador, los reportes con verificaciones y la conservación de intentos inválidos en pruebas cinemáticas son buenas bases. La siguiente iteración debería concentrarse en confiabilidad de resultados y registros, seguida por pruebas de integración y entrega reproducible.

## Evidencia ejecutada

- La suite completa pasó con el entorno Conda `adquisicion-mms`, Python 3.13.15, usando `python -X utf8 -m tests.test_algoritmos`.
- `python -m unittest discover -s tests -v` ejecutó cero pruebas: las comprobaciones actuales son funciones y un `main()`, sin casos `unittest.TestCase`.
- El `.venv` existente no tiene NumPy. El entorno Conda sí tiene las versiones declaradas de NumPy, PyQt6 y pyqtgraph.
- La consola sin UTF-8 falla al imprimir `≥`; las comprobaciones de guardado ya habían pasado antes de ese error de salida.
- Se añadieron casos únicamente en memoria para comprobar NaN, movimientos STS lentos y pérdida de un paquete del giroscopio. No se agregaron pruebas al repositorio.
- Se comprobaron métodos de interfaz con objetos falsos en memoria. No se abrió la aplicación ni se conectó un sensor físico.
- No se construyó ni se probó el instalador. El manual reconoce pendiente la validación con sensor real.

## Mejoras priorizadas

P1 significa alta prioridad para la siguiente iteración; P2, mejora importante posterior. Las prioridades reflejan los hallazgos de esta revisión, no una certificación del producto.

| Prioridad | Hallazgo y evidencia local | Cambio propuesto |
|---|---|---|
| P1 | Un golpe con `acc_x=NaN` durante el movimiento devuelve `valid=True`, velocidad `nan` y comprobación de deriva `ok`. `core/pipeline.py:40`, `core/kinematics.py:98` y `:395`. | Validar finitud de entradas antes de actualizar orientación y de todas las métricas antes de aceptar resultados. Conservar el motivo de rechazo y evitar contaminar el estado del procesador. |
| P1 | Simulación y adquisición real guardan en las mismas rutas y sin origen explícito. Los intentos simulados pueden entrar en comparaciones y la calibración simulada puede reemplazar la real. `ui/main_window.py:223`, `:294`; `core/storage.py:28`. | Carpeta y calibración independientes para simulación, marca visible en pantalla/reportes y campo `data_source` en registros. |
| P1 | Al perder las muestras 9–11 solo del giroscopio, aceleración 9 se empareja con giro 12; el desfase continúa con `paired=True` y cero fallbacks. `core/imu_pairing.py:47`. El propio módulo reconoce esta limitación. | Verificar qué información temporal ofrece el SDK y usarla si permite sincronización real. Detectar pérdida asimétrica y representar la incertidumbre; no presentar FIFO como garantía de simultaneidad. Incorporar calidad de giroscopio al veredicto. |
| P2 | Perder dos muestras durante el vuelo de un salto sintético de 30 cm produce 27,09 cm y un resultado válido con «Sin muestras perdidas durante el vuelo». El reloj estima pérdidas a partir de llegada al PC y su umbral omite pérdidas pequeñas. `core/sample_clock.py:69`, `:102`. | Evaluar información temporal del dispositivo y cuantificar incertidumbre. Cambiar el lenguaje del reporte a «no se detectaron pérdidas» cuando solo hay una estimación; ampliar regresiones de pérdidas pequeñas y cambios de latencia. |
| P2 | Un STS sintético de 40 cm y 1,5 s termina antes de completar el ascenso: devuelve 8,64 cm e intento inválido; a 2 s no entrega resultado. El caso de 1 s sí mide aproximadamente 40 cm. `core/kinematics.py:137`, `:165`. | Detección y criterios de finalización específicos para STS; cubrir movimientos lentos y evitar equiparar baja aceleración con reposo. No se mostró ese ascenso incorrecto como válido. |
| P2 | Preparación permite iniciar con sensor desconectado; calibración acepta cuaternión inicial u obsoleto. Comprobado con métodos reales y objetos falsos. `ui/main_window.py:802`, `:276`, `:223`. | Exigir señal reciente, procesador inicializado y reposo verificable para calibrar; centralizar las precondiciones de captura. La referencia actual afecta la indicación de colocación, no directamente el cálculo de potencia. |
| P2 | La búsqueda BLE puede arrancar mientras una conexión anterior continúa bloqueada. Además, cerrar/reconfigurar espera hasta 5–8 s en el hilo gráfico. `ui/sensor_dialog.py:60`, `:95`; `ui/main_window.py:137`. | Un controlador común de conexión/búsqueda/cierre con transiciones asincrónicas y estado visible. |
| P2 | Dos instancias pueden elegir el mismo número de intento y sobrescribir IMU/HTML; el número se consulta sin reservar y los destinos se abren con `w`. `core/storage.py:75`, `:105`, `:118`. | Impedir instancias simultáneas sobre la misma carpeta o reservar sesiones de forma atómica; rechazar sobrescrituras. |
| P2 | La recuperación de pendientes hace append y después borrado. Una interrupción entre ambos puede duplicar filas. `core/storage.py:218`, `:232`. JSON de configuración/calibración se escribe directamente. | ID estable por sesión, conciliación idempotente y escrituras temporales con reemplazo atómico. Probar interrupciones y recuperación. |
| P2 | El siguiente participante se calcula solo con archivos del directorio principal; un intento sin muestras puede dejar únicamente un reporte y su ID se puede reutilizar. `core/storage.py:62`; `ui/main_window.py:305`, `:395`. | Un catálogo de participantes/sesiones o incluir todas las fuentes al asignar identificadores. |
| P2 | Gran parte de las pruebas numéricas vive en `tests/test_algoritmos.py:67`, dentro de `main()`. No hay automatización CI versionada. | Convertir comprobaciones a casos descubiertos por un runner y ejecutar una suite Windows automatizada, con casos de error e integración. |
| P2 | README prepara `.venv`, pero el constructor prefiere el Conda personal y después Python del PATH. La versión se mantiene manualmente en tres archivos. `packaging/construir.cmd:5`; `README.md:18`, `:30`. | Un intérprete configurable, preferencia por `.venv`, versión centralizada y construcción verificada en Windows limpio. |

## Organización de agentes y subagentes

Mantendría un coordinador y hasta tres agentes de trabajo activos. Los subagentes son divisiones de trabajo; se pueden ejecutar por turnos o reutilizando cupos. Lanzar todos a la vez aumentaría conflictos sobre archivos compartidos.

| Agente | Subagentes propuestos | Responsabilidad y aceptación |
|---|---|---|
| Coordinador e integración | Revisor independiente al finalizar cada tanda | Fijar contratos, asignar archivos, integrar cambios y comprobar que cada defecto reproducido tiene cobertura. Mantener historial y formatos existentes mediante migraciones explícitas. |
| Confiabilidad de mediciones | Validación numérica; sincronización IMU; detección STS | Propiedad de `pipeline`, `kinematics`, `imu_pairing` y calidad. NaN/Inf nunca producen resultados válidos; pérdidas asimétricas quedan visibles; perfiles lentos tienen comportamiento verificado. |
| Bluetooth y captura | Ciclo de vida BLE; precondiciones/calibración | Propiedad de `sensor_stream`, `sensor_dialog` y cambios acotados en `main_window`. Conexión, scanner y cierre no compiten; captura/calibración requieren datos válidos y recientes; pruebas con sensor falso. |
| Integridad de datos | Separación de simulación; persistencia/recuperación; trazabilidad | Propiedad de `storage` y `config`. Simulación aislada; identificadores estables; sin sobrescrituras; recuperación de pendientes sin duplicación; prueba de restauración. Coordinar con Bluetooth cualquier cambio en `main_window`. |
| QA y validación | Regresión automática; integración Qt; protocolo de validación física | Migrar la suite y verificar cambios independientemente. Documentar matriz de escenarios y comparación con referencia externa. La ejecución con sensor real y método de referencia requiere que esos medios estén disponibles. |
| Entrega Windows y mantenimiento | Build/instalador; documentación/refactor | Constructor portable, versiones coherentes, comprobación de instalación limpia. Después de cubrir comportamientos, dividir `main_window.py` —1.158 líneas— en controladores de conexión/sesión y páginas. |

Cada agente debe entregar: problema reproducido, cambio acotado, pruebas de aceptación, archivos modificados y limitaciones pendientes. Los subagentes que toquen el mismo módulo deben trabajar secuencialmente. Las pruebas nuevas pueden separarse por componente para evitar que todos editen `test_algoritmos.py`.

## Orden de ejecución

1. **Primera tanda:** confiabilidad de mediciones, integridad de datos y Bluetooth/captura, bajo un coordinador. Empezar por NaN, aislamiento de simulación y calidad del emparejamiento IMU. Definir primero el contrato de sesión y de calidad compartido.
2. **Segunda tanda:** QA independiente y entrega Windows. Reproducir fallos anteriores sobre la implementación final, ejecutar toda la suite y comprobar instalación limpia.
3. **Tercera tanda:** validación física y refactor. Comparar mediciones contra referencia externa, registrar errores y repetibilidad; ajustar el algoritmo con esa evidencia. Extraer controladores de la UI una vez protegidos los comportamientos con pruebas.

También conviene guardar un manifiesto por sesión: ID, origen, fecha fijada al iniciar, versiones de aplicación/algoritmo/esquema, sensor, frecuencia/rangos, protocolo, ubicación y calibración utilizada. Añadir respaldo/exportación de una sesión completa y una recuperación verificable.

## Prompts para iniciar la primera tanda

**Coordinador**

> Mejora Adquisición MMS siguiendo REVISION_PROYECTO_2026-10-03.md. Empieza por reproducir los hallazgos P1. Divide el trabajo entre confiabilidad de mediciones, integridad de datos y Bluetooth/captura, con un máximo de tres trabajadores activos. Define contratos y propiedad de archivos antes de editar. Conserva los registros existentes y verifica cada corrección con casos que reproduzcan el fallo. Integra cambios acotados y solicita revisión independiente antes de pasar a refactor o nuevas funciones.

**Confiabilidad de mediciones**

> Reproduce y corrige la aceptación de NaN/Inf, la pérdida asimétrica de giroscopio marcada como emparejada y la detección prematura o ausente de STS lento. Reproduce también un salto de 30 cm con dos muestras perdidas que se acepta como 27,09 cm y evalúa la incertidumbre del reloj. Trabaja en core/pipeline.py, core/kinematics.py, core/imu_pairing.py, core/sample_clock.py y calidad, coordinando contratos con los demás agentes. Añade regresiones independientes y conserva las pruebas sintéticas existentes. Comprueba las capacidades temporales del SDK antes de prometer sincronización. Informa qué queda pendiente de validación con hardware.

**Integridad de datos**

> Separa simulación y mediciones reales, incluida calibración. Introduce un ID estable de sesión y origen explícito, evita sobrescrituras y hace idempotente la recuperación de pendientes. Usa escrituras atómicas para configuración/calibración y preserva compatibilidad con CSV existentes. Trabaja en core/storage.py y core/config.py; acuerda con el coordinador los cambios de UI. Verifica bloqueo de archivo, interrupción y dos instancias usando datos sintéticos temporales.

**Bluetooth y captura**

> Centraliza las precondiciones de captura/calibración: conexión transmitiendo, datos recientes, orientación inicializada y reposo verificable. Coordina búsqueda y reconexión con el cierre real de hilos anteriores; elimina esperas del hilo gráfico. Trabaja en core/sensor_stream.py, ui/sensor_dialog.py y cambios acotados en ui/main_window.py. Reproduce con sensores falsos conexión lenta, desconexión, calibración sin datos y cancelación. Coordina con el agente de datos para no editar simultáneamente la finalización de sesión.

## Fuentes técnicas consultadas

- Para convertir la suite a pruebas descubribles, `unittest` ofrece `TestCase` y mecanismos de descubrimiento: [documentación oficial de Python](https://docs.python.org/3/library/unittest.html).
- Para coordinar el cierre asincrónico, Qt expone señales como `finished` y advierte que la interrupción solicitada es cooperativa: [documentación oficial de QThread](https://doc.qt.io/qt-6/qthread.html).
- Si la persistencia crece, una opción es guardar el catálogo/resumen en SQLite y mantener los CSV como exportación. Es una decisión posterior al diseño del contrato de sesión: [control de transacciones de sqlite3](https://docs.python.org/3/library/sqlite3.html#transaction-control).

La desconexión durante una prueba cronometrada no se incorpora al CSV resumen en el flujo actual: `ui/main_window.py:344` exige que no haya `abort_reason`. No se reporta como un defecto de comparación. Para trazabilidad futura, sí conviene registrar todos los intentos con su validez y motivo.
